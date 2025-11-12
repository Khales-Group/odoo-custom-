from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)


class TestDeepSeekService(TransactionCase):
    """Test cases for DeepSeek LLM service."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        # Create test API key
        self.api_key = self.env['llm.api.key'].create({
            'name': 'Test DeepSeek Key',
            'api_key': 'test_deepseek_key_12345',
            'is_active': True,
        })
        
        # Create test provider
        self.provider = self.env['llm.provider'].create({
            'name': 'Test DeepSeek Provider',
            'code': 'deepseek',
            'api_base_url': 'https://api.deepseek.com/v1',
            'api_key_id': self.api_key.id,
            'is_active': True,
        })
        
        # Create test model
        self.model = self.env['llm.provider.model'].create({
            'name': 'Test DeepSeek Chat',
            'model_code': 'deepseek-chat',
            'provider_type': 'deepseek',
            'is_active': True,
            'supports_chat': True,
            'supports_text_generation': True,
            'supports_embeddings': False,
            'supports_streaming': True,
            'supports_function_calling': False,
            'max_tokens': 4096,
            'context_length': 32768,
            'input_cost_per_1k_tokens': 0.00014,
            'output_cost_per_1k_tokens': 0.00028,
            'description': 'Test DeepSeek Chat model',
        })
        
        # Set default model for provider
        self.provider.default_model_id = self.model
        
        # Create DeepSeek service
        self.deepseek_service = self.env['llm.deepseek.service'].create({
            'api_type': 'deepseek',
        })

    def test_service_creation(self):
        """Test DeepSeek service creation."""
        self.assertEqual(self.deepseek_service.provider_code, 'deepseek')
        self.assertEqual(self.deepseek_service.provider_name, 'DeepSeek AI')
        self.assertEqual(self.deepseek_service.api_type, 'deepseek')

    def test_get_api_endpoint(self):
        """Test API endpoint retrieval."""
        # Test DeepSeek AI endpoint
        self.deepseek_service.api_type = 'deepseek'
        endpoint = self.deepseek_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.deepseek.com/v1')
        
        # Test Together AI endpoint
        self.deepseek_service.api_type = 'together'
        endpoint = self.deepseek_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.together.xyz/v1')
        
        # Test Replicate endpoint
        self.deepseek_service.api_type = 'replicate'
        endpoint = self.deepseek_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.replicate.com/v1')
        
        # Test Hugging Face endpoint
        self.deepseek_service.api_type = 'huggingface'
        endpoint = self.deepseek_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api-inference.huggingface.co')
        
        # Test custom endpoint
        self.deepseek_service.api_type = 'custom'
        self.deepseek_service.custom_api_url = 'https://custom.deepseek.api.com'
        endpoint = self.deepseek_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://custom.deepseek.api.com')

    def test_get_headers(self):
        """Test headers generation."""
        headers = self.deepseek_service.get_headers()
        
        self.assertIn('Content-Type', headers)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertIn('Authorization', headers)
        self.assertTrue(headers['Authorization'].startswith('Bearer '))
        self.assertIn('User-Agent', headers)
        self.assertEqual(headers['User-Agent'], 'Odoo-AI-Automation/1.0')

    def test_model_mapping(self):
        """Test model name mapping."""
        # Test DeepSeek AI mapping
        self.deepseek_service.api_type = 'deepseek'
        mapped_model = self.deepseek_service.get_model_mapping('deepseek-chat')
        self.assertEqual(mapped_model, 'deepseek-chat')
        
        # Test Together AI mapping
        self.deepseek_service.api_type = 'together'
        mapped_model = self.deepseek_service.get_model_mapping('deepseek-chat')
        self.assertEqual(mapped_model, 'deepseek-ai/deepseek-chat')
        
        # Test Replicate mapping
        self.deepseek_service.api_type = 'replicate'
        mapped_model = self.deepseek_service.get_model_mapping('deepseek-chat')
        self.assertEqual(mapped_model, 'deepseek-ai/deepseek-chat')
        
        # Test Hugging Face mapping
        self.deepseek_service.api_type = 'huggingface'
        mapped_model = self.deepseek_service.get_model_mapping('deepseek-chat')
        self.assertEqual(mapped_model, 'deepseek-ai/deepseek-chat')

    def test_prepare_deepseek_request(self):
        """Test DeepSeek request preparation."""
        self.deepseek_service.api_type = 'deepseek'
        request_data = self.deepseek_service._prepare_deepseek_request(
            prompt="Test prompt",
            model="deepseek-chat",
            max_tokens=100,
            temperature=0.7
        )
        
        self.assertEqual(request_data['model'], 'deepseek-chat')
        self.assertEqual(request_data['max_tokens'], 100)
        self.assertEqual(request_data['temperature'], 0.7)
        self.assertEqual(request_data['top_p'], 1.0)
        self.assertFalse(request_data['stream'])
        self.assertIn('messages', request_data)
        self.assertEqual(len(request_data['messages']), 1)
        self.assertEqual(request_data['messages'][0]['role'], 'user')
        self.assertEqual(request_data['messages'][0]['content'], 'Test prompt')

    def test_prepare_deepseek_chat_request(self):
        """Test DeepSeek chat request preparation."""
        self.deepseek_service.api_type = 'deepseek'
        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'Hello'}
        ]
        
        request_data = self.deepseek_service._prepare_deepseek_chat_request(
            messages=messages,
            model="deepseek-chat",
            max_tokens=100,
            temperature=0.7
        )
        
        self.assertEqual(request_data['model'], 'deepseek-chat')
        self.assertEqual(request_data['max_tokens'], 100)
        self.assertEqual(request_data['temperature'], 0.7)
        self.assertEqual(request_data['top_p'], 1.0)
        self.assertFalse(request_data['stream'])
        self.assertEqual(request_data['messages'], messages)

    def test_prepare_together_request(self):
        """Test Together AI request preparation."""
        self.deepseek_service.api_type = 'together'
        request_data = self.deepseek_service._prepare_together_request(
            prompt="Test prompt",
            model="deepseek-chat",
            max_tokens=100,
            temperature=0.7
        )
        
        self.assertEqual(request_data['model'], 'deepseek-ai/deepseek-chat')
        self.assertEqual(request_data['prompt'], 'Test prompt')
        self.assertEqual(request_data['max_tokens'], 100)
        self.assertEqual(request_data['temperature'], 0.7)
        self.assertEqual(request_data['top_p'], 1.0)
        self.assertFalse(request_data['stream'])

    def test_prepare_replicate_request(self):
        """Test Replicate request preparation."""
        self.deepseek_service.api_type = 'replicate'
        request_data = self.deepseek_service._prepare_replicate_request(
            prompt="Test prompt",
            model="deepseek-chat",
            max_tokens=100,
            temperature=0.7
        )
        
        self.assertEqual(request_data['version'], 'deepseek-ai/deepseek-chat')
        self.assertIn('input', request_data)
        self.assertEqual(request_data['input']['prompt'], 'Test prompt')
        self.assertEqual(request_data['input']['max_tokens'], 100)
        self.assertEqual(request_data['input']['temperature'], 0.7)
        self.assertEqual(request_data['input']['top_p'], 1.0)

    def test_prepare_huggingface_request(self):
        """Test Hugging Face request preparation."""
        self.deepseek_service.api_type = 'huggingface'
        request_data = self.deepseek_service._prepare_huggingface_request(
            prompt="Test prompt",
            model="deepseek-chat",
            max_tokens=100,
            temperature=0.7
        )
        
        self.assertEqual(request_data['inputs'], 'Test prompt')
        self.assertIn('parameters', request_data)
        self.assertEqual(request_data['parameters']['max_new_tokens'], 100)
        self.assertEqual(request_data['parameters']['temperature'], 0.7)
        self.assertEqual(request_data['parameters']['top_p'], 1.0)
        self.assertTrue(request_data['parameters']['do_sample'])

    def test_parse_response(self):
        """Test response parsing."""
        # Test DeepSeek AI response
        self.deepseek_service.api_type = 'deepseek'
        response_data = {
            'choices': [{
                'message': {
                    'content': 'Test response content'
                }
            }]
        }
        result = self.deepseek_service._parse_response(response_data)
        self.assertEqual(result, 'Test response content')
        
        # Test Together AI response
        self.deepseek_service.api_type = 'together'
        response_data = {
            'choices': [{
                'text': 'Test response text'
            }]
        }
        result = self.deepseek_service._parse_response(response_data)
        self.assertEqual(result, 'Test response text')
        
        # Test Replicate response
        self.deepseek_service.api_type = 'replicate'
        response_data = {
            'output': ['Test replicate output']
        }
        result = self.deepseek_service._parse_response(response_data)
        self.assertEqual(result, 'Test replicate output')
        
        # Test Hugging Face response
        self.deepseek_service.api_type = 'huggingface'
        response_data = [{
            'generated_text': 'Test huggingface text'
        }]
        result = self.deepseek_service._parse_response(response_data)
        self.assertEqual(result, 'Test huggingface text')

    def test_parse_chat_response(self):
        """Test chat response parsing."""
        # Test DeepSeek AI chat response
        self.deepseek_service.api_type = 'deepseek'
        response_data = {
            'choices': [{
                'message': {
                    'content': 'Test chat response',
                    'role': 'assistant'
                },
                'finish_reason': 'stop'
            }],
            'usage': {
                'prompt_tokens': 10,
                'completion_tokens': 5,
                'total_tokens': 15
            }
        }
        result = self.deepseek_service._parse_chat_response(response_data)
        
        self.assertEqual(result['content'], 'Test chat response')
        self.assertEqual(result['role'], 'assistant')
        self.assertEqual(result['finish_reason'], 'stop')
        self.assertEqual(result['usage'], response_data['usage'])

    def test_messages_to_prompt(self):
        """Test message to prompt conversion."""
        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'What is 2+2?'},
            {'role': 'assistant', 'content': '2+2 equals 4.'},
            {'role': 'user', 'content': 'What about 3+3?'}
        ]
        
        prompt = self.deepseek_service._messages_to_prompt(messages)
        expected = "System: You are a helpful assistant.\n\nUser: What is 2+2?\n\nAssistant: 2+2 equals 4.\n\nUser: What about 3+3?\n\nAssistant: "
        self.assertEqual(prompt, expected)

    def test_get_available_models(self):
        """Test available models retrieval."""
        models = self.deepseek_service.get_available_models()
        
        # Check that we have the expected number of models
        self.assertEqual(len(models), 10)
        
        # Check specific models
        model_codes = [model['code'] for model in models]
        expected_codes = [
            'deepseek-chat',
            'deepseek-coder',
            'deepseek-coder-instruct',
            'deepseek-coder-33b-instruct',
            'deepseek-coder-6.7b-instruct',
            'deepseek-coder-1.3b-instruct',
            'deepseek-llm-7b-chat',
            'deepseek-llm-67b-chat',
            'deepseek-math-7b-instruct',
            'deepseek-math-67b-instruct'
        ]
        
        for code in expected_codes:
            self.assertIn(code, model_codes)
        
        # Check model properties
        chat_model = next(m for m in models if m['code'] == 'deepseek-chat')
        self.assertEqual(chat_model['name'], 'DeepSeek Chat')
        self.assertEqual(chat_model['context_length'], 32768)
        self.assertTrue(chat_model['supports_chat'])
        self.assertTrue(chat_model['supports_text_generation'])

    def test_embeddings_not_supported(self):
        """Test that embeddings are not supported."""
        with self.assertRaises(UserError) as context:
            self.deepseek_service.get_embeddings("Test text")
        
        self.assertIn('Embeddings are not currently supported', str(context.exception))

    def test_connection_test_without_provider(self):
        """Test connection test without active provider."""
        # Remove the provider to test error handling
        self.provider.is_active = False
        
        with self.assertRaises(UserError) as context:
            self.deepseek_service.test_connection()
        
        self.assertIn('No active provider found', str(context.exception))

    def test_service_inheritance(self):
        """Test that the service properly inherits from base service."""
        # Test that provider code is computed correctly
        self.assertEqual(self.deepseek_service.provider_code, 'deepseek')
        
        # Test that provider name is computed correctly
        self.assertEqual(self.deepseek_service.provider_name, 'DeepSeek AI')
        
        # Test that the service can access base service methods
        self.assertIsNotNone(self.deepseek_service.get_active_provider())
        self.assertIsNotNone(self.deepseek_service.get_api_key())
        self.assertIsNotNone(self.deepseek_service.get_base_url())
        self.assertIsNotNone(self.deepseek_service.get_default_model())

    def test_model_specialization(self):
        """Test model specialization capabilities."""
        # Test code generation model
        coder_model = next(m for m in self.deepseek_service.get_available_models() 
                          if m['code'] == 'deepseek-coder')
        self.assertIn('code generation', coder_model['description'].lower())
        
        # Test math model
        math_model = next(m for m in self.deepseek_service.get_available_models() 
                         if m['code'] == 'deepseek-math-7b-instruct')
        self.assertIn('mathematical reasoning', math_model['description'].lower())
        
        # Test chat model
        chat_model = next(m for m in self.deepseek_service.get_available_models() 
                         if m['code'] == 'deepseek-chat')
        self.assertIn('general purpose', chat_model['description'].lower())

    def test_cost_optimization(self):
        """Test cost optimization features."""
        models = self.deepseek_service.get_available_models()
        
        # Check that smaller models have lower costs
        small_model = next(m for m in models if m['code'] == 'deepseek-coder-1.3b-instruct')
        large_model = next(m for m in models if m['code'] == 'deepseek-coder-33b-instruct')
        
        # Small model should have lower cost than large model
        self.assertLess(small_model['input_cost_per_1k_tokens'], 
                       large_model['input_cost_per_1k_tokens'])
        self.assertLess(small_model['output_cost_per_1k_tokens'], 
                       large_model['output_cost_per_1k_tokens'])

    def test_context_length_variations(self):
        """Test context length variations across models."""
        models = self.deepseek_service.get_available_models()
        
        # Chat models should have longer context
        chat_model = next(m for m in models if m['code'] == 'deepseek-chat')
        coder_model = next(m for m in models if m['code'] == 'deepseek-coder')
        
        # Chat models have 32K context, Coder models have 16K
        self.assertEqual(chat_model['context_length'], 32768)
        self.assertEqual(coder_model['context_length'], 16384) 