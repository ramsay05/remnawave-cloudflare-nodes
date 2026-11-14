import json
import logging
import unittest
from unittest.mock import patch

import httpx
from cloudflare import AsyncCloudflare
from cloudflare import PermissionDeniedError

from src.cloudflare_dns import CloudflareClient, DNSManager
from src.panel.client import RemnawaveClient


IP = "192.0.2.1"
HOST_UUID = "123e4567-e89b-42d3-a456-426614174000"


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_actions_accept_204_without_json(self):
        for action in ("enable", "disable"):
            with self.subTest(action=action):
                def handler(request):
                    self.assertEqual(request.method, "POST")
                    self.assertEqual(request.url.path, f"/api/hosts/bulk/{action}")
                    self.assertEqual(request.headers["Authorization"], "Bearer test-token")
                    self.assertEqual(json.loads(request.content), {"uuids": [HOST_UUID]})
                    return httpx.Response(204)

                client = object.__new__(RemnawaveClient)
                client.api_url = "https://panel.example.com"
                client.api_key = "test-token"
                client.logger = logging.getLogger(__name__)
                transport_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                with patch("src.panel.client.httpx.AsyncClient", return_value=transport_client):
                    try:
                        result = await getattr(client, f"{action}_hosts")([HOST_UUID])
                    except json.JSONDecodeError:
                        self.fail("A documented 204 success must not be parsed as JSON")
                self.assertEqual(result, [])

    async def test_bulk_action_propagates_http_error(self):
        client = object.__new__(RemnawaveClient)
        client.api_url = "https://panel.example.com"
        client.api_key = "test-token"
        client.logger = logging.getLogger(__name__)
        transport_client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"message": "Forbidden"})))
        with patch("src.panel.client.httpx.AsyncClient", return_value=transport_client):
            with self.assertRaises(httpx.HTTPStatusError):
                await client.disable_hosts([HOST_UUID])

    async def test_legacy_bulk_json_remains_supported(self):
        for payload in ([], {"response": []}):
            with self.subTest(payload=payload):
                client = object.__new__(RemnawaveClient)
                client.api_url = "https://panel.example.com"
                client.api_key = "test-token"
                client.logger = logging.getLogger(__name__)
                transport_client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json=payload)))
                with patch("src.panel.client.httpx.AsyncClient", return_value=transport_client):
                    self.assertEqual(await client.enable_hosts([HOST_UUID]), [])


class DNSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Keep SDK telemetry independent of the test machine's OS discovery.
        platform_patch = patch("cloudflare._base_client.get_platform", return_value="Windows")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)
        headers_patch = patch("cloudflare._base_client.platform_headers", return_value={})
        headers_patch.start()
        self.addCleanup(headers_patch.stop)
        self.records = []
        self.fail_method = None
        self.writes = []
        self.client = CloudflareClient("test-token", rate_limit_delay=0, max_retries=1)
        await self.client.cf.close()
        self.client.cf = AsyncCloudflare(
            api_token="test-token", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handle)),
        )
        self.manager = DNSManager(self.client)

    async def asyncTearDown(self):
        await self.client.cf.close()

    def record(self, ttl=120, proxied=False):
        return {"id": "record1", "name": "vpn.example.com", "type": "A",
                "content": IP, "ttl": ttl, "proxied": proxied,
                "comment": "keep this", "tags": ["owner:test"]}

    def handle(self, request):
        self.assertEqual(request.headers["Authorization"], "Bearer test-token")
        self.assertTrue(request.url.path.startswith("/client/v4/zones/zone1/dns_records"))
        if request.method == self.fail_method:
            return httpx.Response(403, json={"success": False, "errors": [{"code": 10000, "message": "Forbidden"}]})
        if request.method == "GET":
            self.assertEqual(request.url.params["type"], "A")
            self.assertEqual(request.url.params.get("name") or request.url.params.get("name.exact"), "vpn.example.com")
            page = int(request.url.params.get("page", "1"))
            self.assertLessEqual(page, 2)
            return httpx.Response(200, json={"success": True, "errors": [], "messages": [],
                "result": self.records if page == 1 else [], "result_info": {"page": page, "per_page": 100, "count": len(self.records) if page == 1 else 0, "total_count": len(self.records), "total_pages": 1}})
        self.writes.append((request.method, json.loads(request.content) if request.content else None))
        if request.method == "DELETE":
            record_id = request.url.path.rsplit("/", 1)[1]
            self.records = [r for r in self.records if r["id"] != record_id]
            result = {"id": record_id}
        elif request.method == "POST":
            result = {**self.record(), **json.loads(request.content)}
            self.records.append(result)
        else:
            self.assertEqual(request.method, "PATCH", "Preserve unmanaged metadata with a partial update")
            self.records[0].update(json.loads(request.content))
            result = self.records[0]
        return httpx.Response(200, json={"success": True, "errors": [], "messages": [], "result": result})

    async def sync(self, healthy, ttl=60, proxied=False):
        return await self.manager.sync_dns_records("zone1", "vpn", "example.com", [IP], healthy, ttl, proxied)

    async def test_deleted_last_record_is_not_active(self):
        self.records = [self.record()]
        self.assertEqual(await self.sync(set()), set())
        self.assertEqual(self.records, [])

    async def test_failed_create_does_not_publish_ip(self):
        self.fail_method = "POST"
        self.assertEqual(await self.sync({IP}), set())

    async def test_failed_delete_keeps_ip_active(self):
        self.records = [self.record()]
        self.fail_method = "DELETE"
        self.assertEqual(await self.sync(set()), {IP})

    async def test_successful_create_publishes_ip(self):
        self.assertEqual(await self.sync({IP}), {IP})
        self.assertEqual(self.records[0]["ttl"], 60)

    async def test_existing_record_ttl_is_updated(self):
        self.records = [self.record()]
        self.assertEqual(await self.sync({IP}), {IP})
        self.assertEqual(self.records[0]["ttl"], 60)
        self.assertEqual(self.records[0]["comment"], "keep this")

    async def test_existing_record_proxy_uses_auto_ttl(self):
        self.records = [self.record()]
        await self.sync({IP}, proxied=True)
        self.assertTrue(self.records[0]["proxied"])
        self.assertEqual(self.records[0]["ttl"], 1)

    async def test_new_proxied_record_uses_auto_ttl(self):
        await self.sync({IP}, proxied=True)
        self.assertEqual(self.records[0]["ttl"], 1)

    async def test_unchanged_record_does_not_write(self):
        self.records = [self.record(ttl=60)]
        await self.sync({IP})
        self.assertEqual(self.writes, [])

    async def test_failed_update_keeps_published_ip(self):
        self.records = [self.record()]
        self.fail_method = "PATCH"
        self.assertEqual(await self.sync({IP}), {IP})
        self.assertEqual(self.records[0]["ttl"], 120)

    async def test_read_failure_aborts_instead_of_disabling_hosts(self):
        self.fail_method = "GET"
        with self.assertRaises(PermissionDeniedError):
            await self.sync({IP})

    async def test_final_read_failure_does_not_return_assumed_state(self):
        original = self.handle
        reads = 0

        def fail_second_read(request):
            nonlocal reads
            if request.method == "GET" and request.url.params.get("page", "1") == "1":
                reads += 1
                if reads == 2:
                    self.fail_method = "GET"
            return original(request)

        await self.client.cf.close()
        self.client.cf = AsyncCloudflare(api_token="test-token", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(fail_second_read)))
        with self.assertRaises(PermissionDeniedError):
            await self.sync({IP})

    async def test_existing_proxied_record_does_not_write_repeatedly(self):
        self.records = [self.record(ttl=1, proxied=True)]
        await self.sync({IP}, ttl=60, proxied=True)
        self.assertEqual(self.writes, [])

    async def test_duplicate_records_are_all_removed(self):
        self.records = [self.record(), {**self.record(), "id": "record2"}]
        self.assertEqual(await self.sync(set()), set())
        self.assertEqual(self.records, [])

    async def test_sdk_reads_all_dns_pages(self):
        def paginated(request):
            page = int(request.url.params.get("page", "1"))
            self.assertIn(page, (1, 2, 3))
            result = {**self.record(), "id": f"record{page}", "content": f"192.0.2.{page}"}
            return httpx.Response(200, json={"success": True, "errors": [], "messages": [],
                "result": [result] if page <= 2 else [], "result_info": {"page": page, "per_page": 1,
                "count": 1 if page <= 2 else 0, "total_count": 2, "total_pages": 2}})

        await self.client.cf.close()
        self.client.cf = AsyncCloudflare(api_token="test-token", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(paginated)))
        records = await self.client.get_dns_records("zone1", name="vpn.example.com")
        self.assertEqual({r["content"] for r in records}, {"192.0.2.1", "192.0.2.2"})

    async def test_zone_lookup_request(self):
        def zones(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/client/v4/zones")
            self.assertEqual(request.url.params["name"], "example.com")
            return httpx.Response(200, json={"success": True, "errors": [], "messages": [],
                "result": [{"id": "zone1", "name": "example.com"}],
                "result_info": {"page": 1, "per_page": 20, "total_pages": 1}})

        await self.client.cf.close()
        self.client.cf = AsyncCloudflare(api_token="test-token", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(zones)))
        self.assertEqual(await self.client.get_zone_id_by_domain("example.com"), "zone1")


if __name__ == "__main__":
    unittest.main()
