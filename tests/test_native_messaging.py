"""
Tests for Browser Extension v2 - Native Messaging

Tests for native messaging host functionality.
"""

import json
import struct
import pytest
from io import BytesIO
from unittest.mock import Mock, patch, MagicMock


# ============================================================================
# Test NativeMessage
# ============================================================================

class TestNativeMessage:
    """Tests for NativeMessage dataclass."""
    
    def test_to_dict_basic(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage(type="test")
        result = msg.to_dict()
        
        assert result == {"type": "test"}
    
    def test_to_dict_with_data(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage(type="scan", data={"elements": [1, 2, 3]})
        result = msg.to_dict()
        
        assert result["type"] == "scan"
        assert result["data"]["elements"] == [1, 2, 3]
    
    def test_to_dict_with_request_id(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage(type="test", request_id="req_123")
        result = msg.to_dict()
        
        assert result["requestId"] == "req_123"
    
    def test_to_dict_with_error(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage(type="error", error="Something went wrong")
        result = msg.to_dict()
        
        assert result["error"] == "Something went wrong"
    
    def test_from_dict_basic(self):
        from bantz.browser.native_messaging import NativeMessage
        
        data = {"type": "command", "data": {"action": "click"}}
        msg = NativeMessage.from_dict(data)
        
        assert msg.type == "command"
        assert msg.data["action"] == "click"
    
    def test_from_dict_with_request_id(self):
        from bantz.browser.native_messaging import NativeMessage
        
        data = {"type": "test", "requestId": "req_456"}
        msg = NativeMessage.from_dict(data)
        
        assert msg.request_id == "req_456"
    
    def test_from_dict_missing_type(self):
        from bantz.browser.native_messaging import NativeMessage
        
        data = {"data": {"foo": "bar"}}
        msg = NativeMessage.from_dict(data)
        
        assert msg.type == "unknown"
    
    def test_error_response(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage.error_response("Test error", "req_123")
        
        assert msg.type == "error"
        assert msg.error == "Test error"
        assert msg.request_id == "req_123"
    
    def test_success_response(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage.success_response({"result": "ok"}, "req_456")
        
        assert msg.type == "response"
        assert msg.data["result"] == "ok"
        assert msg.request_id == "req_456"


# ============================================================================
# Test NativeMessagingIO
# ============================================================================

class TestNativeMessagingIO:
    """Tests for low-level native messaging I/O."""
    
    def test_write_message_format(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        
        # Create a mock stdout buffer
        mock_buffer = BytesIO()
        
        with patch('sys.stdout') as mock_stdout:
            mock_stdout.buffer = mock_buffer
            
            message = {"type": "test", "data": {"foo": "bar"}}
            NativeMessagingIO.write_message(message)
            
            # Read back
            mock_buffer.seek(0)
            
            # First 4 bytes are length
            length_bytes = mock_buffer.read(4)
            length = struct.unpack("@I", length_bytes)[0]
            
            # Rest is JSON
            json_bytes = mock_buffer.read(length)
            parsed = json.loads(json_bytes.decode("utf-8"))
            
            assert parsed["type"] == "test"
            assert parsed["data"]["foo"] == "bar"
    
    def test_read_message_format(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        
        # Create message
        message = {"type": "test", "value": 123}
        json_bytes = json.dumps(message).encode("utf-8")
        length_bytes = struct.pack("@I", len(json_bytes))
        
        # Create mock stdin buffer
        mock_buffer = BytesIO(length_bytes + json_bytes)
        
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.buffer = mock_buffer
            
            result = NativeMessagingIO.read_message()
            
            assert result["type"] == "test"
            assert result["value"] == 123
    
    def test_read_message_empty(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        
        mock_buffer = BytesIO(b"")
        
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.buffer = mock_buffer
            
            result = NativeMessagingIO.read_message()
            
            assert result is None
    
    def test_read_message_invalid_json(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        
        # Invalid JSON
        invalid_bytes = b"not json at all"
        length_bytes = struct.pack("@I", len(invalid_bytes))
        
        mock_buffer = BytesIO(length_bytes + invalid_bytes)
        
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.buffer = mock_buffer
            
            result = NativeMessagingIO.read_message()
            
            assert result is None


# ============================================================================
# Test NativeMessagingHost
# ============================================================================

class TestNativeMessagingHost:
    """Tests for native messaging host."""
    
    def test_host_creation(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        assert host.handlers == {}
        assert host.running is False
    
    def test_register_handler(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        def my_handler(msg):
            return {"handled": True}
        
        host.register_handler("test", my_handler)
        
        assert "test" in host.handlers
        assert host.handlers["test"] is my_handler
    
    def test_handler_decorator(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        @host.handler("decorated")
        def handle_decorated(msg):
            return {"decorated": True}
        
        assert "decorated" in host.handlers
    
    def test_handle_message_with_handler(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        @host.handler("greet")
        def handle_greet(msg):
            return {"message": f"Hello, {msg.data.get('name', 'World')}!"}
        
        response = host.handle_message({
            "type": "greet",
            "data": {"name": "Test"},
        })
        
        assert response["data"]["message"] == "Hello, Test!"
    
    def test_handle_message_with_request_id(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        @host.handler("echo")
        def handle_echo(msg):
            return msg.data
        
        response = host.handle_message({
            "type": "echo",
            "data": {"value": 42},
            "requestId": "req_789",
        })
        
        assert response["requestId"] == "req_789"
        assert response["data"]["value"] == 42
    
    def test_handle_message_unknown_type(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        response = host.handle_message({
            "type": "unknown_command",
        })
        
        assert response["type"] == "error"
        assert "unknown_command" in response["error"].lower()
    
    def test_handle_message_handler_exception(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        @host.handler("fail")
        def handle_fail(msg):
            raise ValueError("Intentional error")
        
        response = host.handle_message({
            "type": "fail",
        })
        
        assert response["type"] == "error"
        assert "Intentional error" in response["error"]
    
    def test_handle_message_with_daemon_callback(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        callback = Mock(return_value={"forwarded": True})
        host.set_daemon_callback(callback)
        
        response = host.handle_message({
            "type": "forward_me",
            "data": {"test": True},
        })
        
        callback.assert_called_once()
        assert response == {"forwarded": True}
    
    def test_send_command(self):
        from bantz.browser.native_messaging import NativeMessagingHost, NativeMessagingIO
        
        host = NativeMessagingHost()
        
        with patch.object(NativeMessagingIO, 'write_message', return_value=True) as mock_write:
            result = host.send_command("scan", {"maxElements": 50}, tab_id=123)
            
            assert result is True
            mock_write.assert_called_once()
            
            call_args = mock_write.call_args[0][0]
            assert call_args["type"] == "command"
            assert call_args["command"] == "scan"
            assert call_args["params"]["maxElements"] == 50
            assert call_args["tabId"] == 123


# ============================================================================
# Test NativeMessagingClient
# ============================================================================

class TestNativeMessagingClient:
    """Tests for native messaging client."""
    
    def test_client_creation(self):
        from bantz.browser.native_messaging import NativeMessagingHost, NativeMessagingClient
        
        host = NativeMessagingHost()
        client = NativeMessagingClient(host)
        
        assert client.host is host
        assert client.request_counter == 0
    
    def test_send_message(self):
        from bantz.browser.native_messaging import (
            NativeMessagingHost,
            NativeMessagingClient,
            NativeMessagingIO,
        )
        
        host = NativeMessagingHost()
        client = NativeMessagingClient(host)
        
        with patch.object(NativeMessagingIO, 'write_message', return_value=True):
            result = client.send("notify", {"text": "Hello"})
            
            assert result is True
    
    def test_handle_response_resolves_future(self):
        from bantz.browser.native_messaging import NativeMessagingHost, NativeMessagingClient
        import asyncio
        
        host = NativeMessagingHost()
        client = NativeMessagingClient(host)
        
        # Manually add a pending request
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        client.pending_requests["req_1"] = future
        
        # Handle response
        handled = client.handle_response({
            "requestId": "req_1",
            "data": {"success": True},
        })
        
        assert handled is True
        assert "req_1" not in client.pending_requests
        
        loop.close()
    
    def test_handle_response_unknown_request_id(self):
        from bantz.browser.native_messaging import NativeMessagingHost, NativeMessagingClient
        
        host = NativeMessagingHost()
        client = NativeMessagingClient(host)
        
        handled = client.handle_response({
            "requestId": "unknown_req",
            "data": {},
        })
        
        assert handled is False


# ============================================================================
# Test create_default_host
# ============================================================================

class TestCreateDefaultHost:
    """Tests for default host creation."""
    
    def test_default_host_has_handlers(self):
        from bantz.browser.native_messaging import create_default_host
        
        host = create_default_host()
        
        assert "ping" in host.handlers
        assert "version" in host.handlers
        assert "log" in host.handlers
    
    def test_ping_handler(self):
        from bantz.browser.native_messaging import create_default_host
        
        host = create_default_host()
        
        response = host.handle_message({"type": "ping"})
        
        assert response["data"]["pong"] is True
        assert "timestamp" in response["data"]
    
    def test_version_handler(self):
        from bantz.browser.native_messaging import create_default_host
        
        host = create_default_host()
        
        response = host.handle_message({"type": "version"})
        
        assert response["data"]["version"] == "2.0.0"
        assert response["data"]["name"] == "bantz_native"
        assert "python_version" in response["data"]
    
    def test_log_handler(self):
        from bantz.browser.native_messaging import create_default_host
        
        host = create_default_host()
        
        response = host.handle_message({
            "type": "log",
            "data": {"level": "info", "text": "Test log message"},
        })
        
        assert response["data"]["logged"] is True


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for native messaging."""
    
    def test_roundtrip_message(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        import struct
        
        # Create a message
        original = {"type": "test", "data": {"value": [1, 2, 3]}}
        json_bytes = json.dumps(original).encode("utf-8")
        length_bytes = struct.pack("@I", len(json_bytes))
        
        # Write to mock buffer
        input_buffer = BytesIO(length_bytes + json_bytes)
        output_buffer = BytesIO()
        
        with patch('sys.stdin') as mock_stdin, \
             patch('sys.stdout') as mock_stdout:
            
            mock_stdin.buffer = input_buffer
            mock_stdout.buffer = output_buffer
            
            # Read
            received = NativeMessagingIO.read_message()
            
            # Modify and write back
            received["data"]["processed"] = True
            NativeMessagingIO.write_message(received)
            
            # Verify output
            output_buffer.seek(0)
            out_length = struct.unpack("@I", output_buffer.read(4))[0]
            out_json = json.loads(output_buffer.read(out_length).decode("utf-8"))
            
            assert out_json["type"] == "test"
            assert out_json["data"]["value"] == [1, 2, 3]
            assert out_json["data"]["processed"] is True
    
    def test_host_message_flow(self):
        from bantz.browser.native_messaging import create_default_host
        
        host = create_default_host()
        
        # Add custom handler
        @host.handler("custom")
        def handle_custom(msg):
            return {"custom_result": msg.data.get("input", "") + "_processed"}
        
        # Test flow
        response = host.handle_message({
            "type": "custom",
            "data": {"input": "test"},
            "requestId": "flow_test_1",
        })
        
        assert response["type"] == "response"
        assert response["data"]["custom_result"] == "test_processed"
        assert response["requestId"] == "flow_test_1"


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_data(self):
        from bantz.browser.native_messaging import NativeMessage
        
        msg = NativeMessage(type="empty")
        result = msg.to_dict()
        
        # Empty data should not be included
        assert "data" not in result or result["data"] == {}
    
    def test_unicode_message(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        import struct
        
        # Turkish text
        message = {"type": "test", "data": {"text": "Türkçe karakter: ğüşıöç"}}
        json_bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")
        length_bytes = struct.pack("@I", len(json_bytes))
        
        input_buffer = BytesIO(length_bytes + json_bytes)
        
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.buffer = input_buffer
            
            result = NativeMessagingIO.read_message()
            
            assert result["data"]["text"] == "Türkçe karakter: ğüşıöç"
    
    def test_large_message(self):
        from bantz.browser.native_messaging import NativeMessagingIO
        import struct
        
        # Large data
        large_data = {"items": list(range(10000))}
        message = {"type": "large", "data": large_data}
        json_bytes = json.dumps(message).encode("utf-8")
        length_bytes = struct.pack("@I", len(json_bytes))
        
        input_buffer = BytesIO(length_bytes + json_bytes)
        
        with patch('sys.stdin') as mock_stdin:
            mock_stdin.buffer = input_buffer
            
            result = NativeMessagingIO.read_message()
            
            assert len(result["data"]["items"]) == 10000
    
    def test_handler_returns_native_message(self):
        from bantz.browser.native_messaging import NativeMessagingHost, NativeMessage
        
        host = NativeMessagingHost()
        
        @host.handler("return_message")
        def handler(msg):
            return NativeMessage(
                type="custom_response",
                data={"special": True},
            )
        
        response = host.handle_message({
            "type": "return_message",
            "requestId": "custom_1",
        })
        
        # Should preserve the request_id
        assert response["requestId"] == "custom_1"
        assert response["type"] == "custom_response"
        assert response["data"]["special"] is True
    
    def test_handler_returns_non_dict(self):
        from bantz.browser.native_messaging import NativeMessagingHost
        
        host = NativeMessagingHost()
        
        @host.handler("return_string")
        def handler(msg):
            return "just a string"
        
        response = host.handle_message({"type": "return_string"})
        
        assert response["data"]["result"] == "just a string"
