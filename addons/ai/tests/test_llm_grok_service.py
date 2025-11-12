from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
import json
import unittest.mock as mock


class TestLLMGrokService(TransactionCase):

    def setUp(self):
        super().setUp()
        # Create a test Grok service
        self.grok_service = self.env['llm.grok.service'].create({
            'name': 'Test Grok Service',
            'api_version': 'v1',
        })

    def test_provider_code_computation(self):
        """Test that provider_code is automatically computed."""
        self.assertEqual(self.grok_service.provider_code, 'grok')
        self.assertEqual(self.grok_service.provider_name, 'xAI Grok')

    def test_api_endpoint_mapping(self):
        """Test API endpoint mapping."""
        endpoint = self.grok_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.x.ai/v1')

    def test_model_mapping(self):
        """Test model code mapping."""
        # Test various model mappings
        self.assertEqual(self.grok_service.get_model_mapping('grok-beta'), 'grok-beta')
        self.assertEqual(self.grok_service.get_model_mapping('grok-2'), 'grok-2')
        self.assertEqual(self.grok_service.get_model_mapping('grok-2-mini'), 'grok-2-mini')
        self.assertEqual(self.grok_service.get_model_mapping('grok-2-vision'), 'grok-2-vision')
        self.assertEqual(self.grok_service.get_model_mapping('grok-2-vision-mini'), 'grok-2-vision-mini')

    def test_request_preparation(self):
        """Test text generation request preparation."""
        request_data = self.grok_service._prepare_text_request(
            'Test prompt', 'grok-2', max_tokens=100, temperature=0.5
        )
        
        expected = {
            'model': 'grok-2',
            'messages': [{'role': 'user', 'content': 'Test prompt'}],
            'max_tokens': 100,
            'temperature': 0.5,
            'top_p': 1.0,
            'stream': False,
        }
        self.assertEqual(request_data, expected)

    def test_chat_request_preparation(self):
        """Test chat completion request preparation."""
        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'Hello'},
        ]
        
        request_data = self.grok_service._prepare_chat_request(
            messages, 'grok-2', max_tokens=100, temperature=0.5
        )
        
        expected = {
            'model': 'grok-2',
            'messages': messages,
            'max_tokens': 100,
            'temperature': 0.5,
            'top_p': 1.0,
            'stream': False,
        }
        self.assertEqual(request_data, expected)

    def test_response_parsing(self):
        """Test text generation response parsing."""
        response_data = {
            'choices': [{
                'message': {
                    'content': 'This is a test response'
                }
            }]
        }
        
        result = self.grok_service._parse_text_response(response_data)
        self.assertEqual(result, 'This is a test response')

    def test_chat_response_parsing(self):
        """Test chat completion response parsing."""
        response_data = {
            'choices': [{
                'message': {
                    'content': 'This is a chat response'
                }
            }],
            'model': 'grok-2',
            'usage': {'total_tokens': 50}
        }
        
        result = self.grok_service._parse_chat_response(response_data)
        expected = {
            'content': 'This is a chat response',
            'role': 'assistant',
            'model': 'grok-2',
            'usage': {'total_tokens': 50}
        }
        self.assertEqual(result, expected)

    def test_embeddings_response_parsing(self):
        """Test embeddings response parsing."""
        response_data = {
            'data': [{
                'embedding': [0.1, 0.2, 0.3]
            }]
        }
        
        result = self.grok_service._parse_embeddings_response(response_data)
        self.assertEqual(result, [0.1, 0.2, 0.3])

    def test_available_models(self):
        """Test available models list."""
        models = self.grok_service.get_available_models()
        
        expected_models = [
            {'code': 'grok-beta', 'name': 'Grok Beta', 'context_length': 8192},
            {'code': 'grok-2', 'name': 'Grok 2', 'context_length': 32768},
            {'code': 'grok-2-mini', 'name': 'Grok 2 Mini', 'context_length': 16384},
            {'code': 'grok-2-vision', 'name': 'Grok 2 Vision', 'context_length': 32768},
            {'code': 'grok-2-vision-mini', 'name': 'Grok 2 Vision Mini', 'context_length': 16384},
        ]
        
        self.assertEqual(len(models), len(expected_models))
        for model in models:
            self.assertIn(model, expected_models)

    def test_embeddings_support(self):
        """Test that embeddings use fallback model."""
        with mock.patch.object(self.grok_service, 'get_api_key', return_value='test_key'):
            with mock.patch('requests.post') as mock_post:
                mock_response = mock.Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    'data': [{'embedding': [0.1, 0.2, 0.3]}]
                }
                mock_post.return_value = mock_response
                
                result = self.grok_service.get_embeddings('test text')
                self.assertEqual(result, [0.1, 0.2, 0.3])

    def test_connection_test(self):
        """Test connection testing functionality."""
        with mock.patch.object(self.grok_service, 'generate_text', return_value='OK'):
            result = self.grok_service.test_connection()
            self.assertTrue(result)

    def test_error_handling(self):
        """Test error handling in API calls."""
        with mock.patch.object(self.grok_service, 'get_api_key', return_value='test_key'):
            with mock.patch('requests.post') as mock_post:
                mock_response = mock.Mock()
                mock_response.status_code = 400
                mock_response.text = 'Bad Request'
                mock_post.return_value = mock_response
                
                with self.assertRaises(UserError):
                    self.grok_service.generate_text('test prompt')

    def test_service_inheritance(self):
        """Test that Grok service properly inherits from base service."""
        # Test that required methods exist
        self.assertTrue(hasattr(self.grok_service, 'generate_text'))
        self.assertTrue(hasattr(self.grok_service, 'chat_completion'))
        self.assertTrue(hasattr(self.grok_service, 'get_embeddings'))
        self.assertTrue(hasattr(self.grok_service, 'test_connection'))
        self.assertTrue(hasattr(self.grok_service, 'log_request'))

    def test_provider_integration(self):
        """Test integration with provider system."""
        # Create a provider model for Grok
        provider_model = self.env['llm.provider.model'].create({
            'name': 'Test Grok Model',
            'model_code': 'grok-2',
            'provider_type': 'grok',
            'is_active': True,
        })
        
        self.assertEqual(provider_model.provider_type, 'grok')
        self.assertEqual(provider_model.model_code, 'grok-2')

    def test_api_version_field(self):
        """Test API version field functionality."""
        # Test default value
        self.assertEqual(self.grok_service.api_version, 'v1')
        
        # Test selection values
        selection_values = dict(self.grok_service._fields['api_version'].selection)
        self.assertIn('v1', selection_values)
        self.assertEqual(selection_values['v1'], 'API v1')

    def test_headers_generation(self):
        """Test headers generation for API requests."""
        with mock.patch.object(self.grok_service, 'get_api_key', return_value='test_key'):
            headers = self.grok_service.get_headers()
            
            expected_headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer test_key',
                'User-Agent': 'Odoo-AI-Automation/1.0',
            }
            self.assertEqual(headers, expected_headers) 