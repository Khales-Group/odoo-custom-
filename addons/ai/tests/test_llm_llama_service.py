from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)


class TestLLMLlamaService(TransactionCase):
    """Test cases for Meta Llama service implementation."""
    
    def setUp(self):
        super().setUp()
        
        # Create test API key
        self.api_key = self.env['llm.api.key'].create({
            'name': 'Test Llama API Key',
            'encrypted_key': 'test_encrypted_key',
            'is_active': True,
        })
        
        # Create test provider
        self.provider = self.env['llm.provider'].create({
            'name': 'Test Llama Provider',
            'code': 'llama',
            'api_base_url': 'https://api.together.xyz/v1',
            'default_model_id': self.env.ref('ai_automation_base.model_llama_3_1_8b').id,
            'api_key_id': self.api_key.id,
            'is_active': True,
        })
        
        # Get Llama service
        self.llama_service = self.env['llm.llama.service']
    
    def test_provider_code_computation(self):
        """Test that provider code is computed correctly."""
        self.assertEqual(self.llama_service.provider_code, 'llama')
        self.assertEqual(self.llama_service.provider_name, 'Meta Llama')
    
    def test_api_endpoint_mapping(self):
        """Test API endpoint mapping for different API types."""
        # Test Together AI
        self.llama_service.api_type = 'together'
        endpoint = self.llama_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.together.xyz/v1')
        
        # Test Replicate
        self.llama_service.api_type = 'replicate'
        endpoint = self.llama_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.replicate.com/v1')
        
        # Test Hugging Face
        self.llama_service.api_type = 'huggingface'
        endpoint = self.llama_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api-inference.huggingface.co')
        
        # Test Perplexity
        self.llama_service.api_type = 'perplexity'
        endpoint = self.llama_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://api.perplexity.ai')
        
        # Test Custom
        self.llama_service.api_type = 'custom'
        self.llama_service.custom_api_url = 'https://custom.api.com'
        endpoint = self.llama_service.get_api_endpoint()
        self.assertEqual(endpoint, 'https://custom.api.com')
    
    def test_model_mapping(self):
        """Test model mapping for different API types."""
        # Test Together AI model mapping
        self.llama_service.api_type = 'together'
        mapped_model = self.llama_service.get_model_mapping('llama-3.1-8b')
        self.assertEqual(mapped_model, 'meta-llama/Llama-3.1-8B-Instruct')
        
        # Test Replicate model mapping
        self.llama_service.api_type = 'replicate'
        mapped_model = self.llama_service.get_model_mapping('llama-3.1-8b')
        self.assertEqual(mapped_model, 'meta/llama-3.1-8b-instruct')
        
        # Test Hugging Face model mapping
        self.llama_service.api_type = 'huggingface'
        mapped_model = self.llama_service.get_model_mapping('llama-3.1-8b')
        self.assertEqual(mapped_model, 'meta-llama/Llama-3.1-8B-Instruct')
        
        # Test Perplexity model mapping
        self.llama_service.api_type = 'perplexity'
        mapped_model = self.llama_service.get_model_mapping('llama-3.1-8b')
        self.assertEqual(mapped_model, 'llama-3.1-8b-instruct')
    
    def test_request_preparation(self):
        """Test request data preparation for different API types."""
        prompt = "Hello, how are you?"
        model = "llama-3.1-8b"
        
        # Test Together AI request
        self.llama_service.api_type = 'together'
        request_data = self.llama_service._prepare_together_request(prompt, model)
        self.assertIn('model', request_data)
        self.assertIn('messages', request_data)
        self.assertEqual(request_data['messages'][0]['content'], prompt)
        
        # Test Replicate request
        self.llama_service.api_type = 'replicate'
        request_data = self.llama_service._prepare_replicate_request(prompt, model)
        self.assertIn('version', request_data)
        self.assertIn('input', request_data)
        self.assertEqual(request_data['input']['prompt'], prompt)
        
        # Test Hugging Face request
        self.llama_service.api_type = 'huggingface'
        request_data = self.llama_service._prepare_huggingface_request(prompt, model)
        self.assertIn('inputs', request_data)
        self.assertIn('parameters', request_data)
        self.assertEqual(request_data['inputs'], prompt)
        
        # Test Perplexity request
        self.llama_service.api_type = 'perplexity'
        request_data = self.llama_service._prepare_perplexity_request(prompt, model)
        self.assertIn('model', request_data)
        self.assertIn('messages', request_data)
        self.assertEqual(request_data['messages'][0]['content'], prompt)
    
    def test_chat_request_preparation(self):
        """Test chat request data preparation."""
        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'Hello, how are you?'}
        ]
        model = "llama-3.1-8b"
        
        # Test Together AI chat request
        self.llama_service.api_type = 'together'
        request_data = self.llama_service._prepare_together_chat_request(messages, model)
        self.assertIn('model', request_data)
        self.assertIn('messages', request_data)
        self.assertEqual(len(request_data['messages']), 2)
        
        # Test Perplexity chat request
        self.llama_service.api_type = 'perplexity'
        request_data = self.llama_service._prepare_perplexity_chat_request(messages, model)
        self.assertIn('model', request_data)
        self.assertIn('messages', request_data)
        self.assertEqual(len(request_data['messages']), 2)
    
    def test_response_parsing(self):
        """Test response parsing for different API types."""
        # Test Together AI response parsing
        self.llama_service.api_type = 'together'
        response_data = {
            'choices': [{'message': {'content': 'I am doing well, thank you!'}}]
        }
        result = self.llama_service._parse_response(response_data)
        self.assertEqual(result, 'I am doing well, thank you!')
        
        # Test Replicate response parsing
        self.llama_service.api_type = 'replicate'
        response_data = {'output': ['I am doing well, thank you!']}
        result = self.llama_service._parse_response(response_data)
        self.assertEqual(result, 'I am doing well, thank you!')
        
        # Test Hugging Face response parsing
        self.llama_service.api_type = 'huggingface'
        response_data = [{'generated_text': 'I am doing well, thank you!'}]
        result = self.llama_service._parse_response(response_data)
        self.assertEqual(result, 'I am doing well, thank you!')
        
        # Test Perplexity response parsing
        self.llama_service.api_type = 'perplexity'
        response_data = {
            'choices': [{'message': {'content': 'I am doing well, thank you!'}}]
        }
        result = self.llama_service._parse_response(response_data)
        self.assertEqual(result, 'I am doing well, thank you!')
    
    def test_chat_response_parsing(self):
        """Test chat response parsing."""
        # Test Together AI chat response parsing
        self.llama_service.api_type = 'together'
        response_data = {
            'choices': [{'message': {'content': 'I am doing well, thank you!'}}],
            'model': 'meta-llama/Llama-3.1-8B-Instruct',
            'usage': {'total_tokens': 50}
        }
        result = self.llama_service._parse_chat_response(response_data)
        self.assertEqual(result['content'], 'I am doing well, thank you!')
        self.assertEqual(result['role'], 'assistant')
        self.assertEqual(result['model'], 'meta-llama/Llama-3.1-8B-Instruct')
        
        # Test Perplexity chat response parsing
        self.llama_service.api_type = 'perplexity'
        response_data = {
            'choices': [{'message': {'content': 'I am doing well, thank you!'}}],
            'model': 'llama-3.1-8b-instruct',
            'usage': {'total_tokens': 50}
        }
        result = self.llama_service._parse_chat_response(response_data)
        self.assertEqual(result['content'], 'I am doing well, thank you!')
        self.assertEqual(result['role'], 'assistant')
        self.assertEqual(result['model'], 'llama-3.1-8b-instruct')
    
    def test_messages_to_prompt_conversion(self):
        """Test conversion of chat messages to prompt string."""
        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'Hello, how are you?'},
            {'role': 'assistant', 'content': 'I am doing well, thank you!'},
            {'role': 'user', 'content': 'What is the weather like?'}
        ]
        
        prompt = self.llama_service._messages_to_prompt(messages)
        
        self.assertIn('System: You are a helpful assistant.', prompt)
        self.assertIn('User: Hello, how are you?', prompt)
        self.assertIn('Assistant: I am doing well, thank you!', prompt)
        self.assertIn('User: What is the weather like?', prompt)
        self.assertIn('Assistant: ', prompt)
    
    def test_available_models(self):
        """Test getting available models for different API types."""
        # Test Together AI models
        self.llama_service.api_type = 'together'
        models = self.llama_service.get_available_models()
        self.assertGreater(len(models), 0)
        self.assertIn('llama-3.1-8b', [m['code'] for m in models])
        self.assertIn('llama-3.1-70b', [m['code'] for m in models])
        
        # Test Replicate models
        self.llama_service.api_type = 'replicate'
        models = self.llama_service.get_available_models()
        self.assertGreater(len(models), 0)
        self.assertIn('llama-3.1-8b', [m['code'] for m in models])
        
        # Test Perplexity models
        self.llama_service.api_type = 'perplexity'
        models = self.llama_service.get_available_models()
        self.assertGreater(len(models), 0)
        self.assertIn('llama-3.1-8b', [m['code'] for m in models])
        self.assertIn('mixtral-8x7b', [m['code'] for m in models])
    
    def test_embeddings_support(self):
        """Test embeddings support for different API types."""
        # Test Together AI embeddings
        self.llama_service.api_type = 'together'
        try:
            # This should not raise an error for Together AI
            self.llama_service.get_embeddings("test text")
        except UserError as e:
            # If it raises an error, it should be about missing API key, not unsupported
            self.assertNotIn('not supported', str(e))
        
        # Test Hugging Face embeddings
        self.llama_service.api_type = 'huggingface'
        try:
            # This should not raise an error for Hugging Face
            self.llama_service.get_embeddings("test text")
        except UserError as e:
            # If it raises an error, it should be about missing API key, not unsupported
            self.assertNotIn('not supported', str(e))
        
        # Test Replicate embeddings (should not support)
        self.llama_service.api_type = 'replicate'
        with self.assertRaises(UserError) as context:
            self.llama_service.get_embeddings("test text")
        self.assertIn('not supported', str(context.exception))
    
    def test_connection_test(self):
        """Test connection testing functionality."""
        # This test will fail without actual API credentials, but we can test the method exists
        self.assertTrue(hasattr(self.llama_service, 'test_connection'))
        
        # Test that the method returns a boolean
        result = self.llama_service.test_connection()
        self.assertIsInstance(result, bool)
    
    def test_error_handling(self):
        """Test error handling in the service."""
        # Test with invalid API type
        self.llama_service.api_type = 'invalid'
        
        # Should handle gracefully
        endpoint = self.llama_service.get_api_endpoint()
        self.assertEqual(endpoint, self.llama_service.get_base_url())
        
        # Test model mapping with invalid API type
        mapped_model = self.llama_service.get_model_mapping('llama-3.1-8b')
        self.assertEqual(mapped_model, 'llama-3.1-8b')  # Should return original model name
    
    def test_service_inheritance(self):
        """Test that the Llama service properly inherits from base service."""
        # Test that required methods exist
        required_methods = [
            'generate_text',
            'chat_completion',
            'get_embeddings',
            'test_connection',
            'get_available_models'
        ]
        
        for method in required_methods:
            self.assertTrue(hasattr(self.llama_service, method))
            self.assertTrue(callable(getattr(self.llama_service, method)))
    
    def test_provider_integration(self):
        """Test integration with the provider system."""
        # Test that the service can get provider configuration
        provider = self.llama_service.get_active_provider()
        self.assertEqual(provider.code, 'llama')
        self.assertTrue(provider.is_active)
        
        # Test that the service can get API key
        api_key = self.llama_service.get_api_key()
        self.assertEqual(api_key, 'test_encrypted_key')
        
        # Test that the service can get base URL
        base_url = self.llama_service.get_base_url()
        self.assertEqual(base_url, 'https://api.together.xyz/v1')
        
        # Test that the service can get default model
        default_model = self.llama_service.get_default_model()
        self.assertEqual(default_model, 'llama-3.1-8b') 