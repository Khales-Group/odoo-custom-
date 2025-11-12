from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
import requests
from typing import Dict, List, Optional, Any, Union
import time

_logger = logging.getLogger(__name__)


class LLMLlamaService(models.Model):
    """Service implementation for Meta Llama models via various APIs."""
    
    _name = 'llm.llama.service'
    _description = 'Meta Llama Service'
    _inherit = 'llm.base.service'
    
    # Provider-specific configuration
    api_type = fields.Selection([
        ('together', 'Together AI'),
        ('replicate', 'Replicate'),
        ('huggingface', 'Hugging Face'),
        ('perplexity', 'Perplexity AI'),
        ('custom', 'Custom API'),
    ], string='API Type', required=True, default='together',
       help='Type of API to use for Llama models')
    
    custom_api_url = fields.Char(
        string='Custom API URL',
        help='Custom API endpoint URL (for custom API type)'
    )
    
    def get_api_endpoint(self, model: str = None) -> str:
        """Get the appropriate API endpoint based on API type."""
        if self.api_type == 'together':
            return 'https://api.together.xyz/v1'
        elif self.api_type == 'replicate':
            return 'https://api.replicate.com/v1'
        elif self.api_type == 'huggingface':
            return 'https://api-inference.huggingface.co'
        elif self.api_type == 'perplexity':
            return 'https://api.perplexity.ai'
        elif self.api_type == 'custom':
            return self.custom_api_url or self.get_base_url()
        else:
            return self.get_base_url()
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        api_key = self.get_api_key()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        
        # Add provider-specific headers
        if self.api_type == 'together':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        elif self.api_type == 'replicate':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        elif self.api_type == 'huggingface':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        elif self.api_type == 'perplexity':
            headers['User-Agent'] = 'Odoo-AI-Automation/1.0'
        
        return headers
    
    def get_model_mapping(self, model: str = None) -> str:
        """Map Odoo model codes to provider-specific model names."""
        if not model:
            model = self.get_default_model()
        
        # Together AI model mappings
        together_models = {
            'llama-3.1-8b': 'meta-llama/Llama-3.1-8B-Instruct',
            'llama-3.1-70b': 'meta-llama/Llama-3.1-70B-Instruct',
            'llama-3.1-405b': 'meta-llama/Llama-3.1-405B-Instruct',
            'llama-3.1-8b-instruct': 'meta-llama/Llama-3.1-8B-Instruct',
            'llama-3.1-70b-instruct': 'meta-llama/Llama-3.1-70B-Instruct',
            'llama-3.1-405b-instruct': 'meta-llama/Llama-3.1-405B-Instruct',
            'llama-2-7b': 'meta-llama/Llama-2-7b-chat-hf',
            'llama-2-13b': 'meta-llama/Llama-2-13b-chat-hf',
            'llama-2-70b': 'meta-llama/Llama-2-70b-chat-hf',
            'llama-2-7b-chat': 'meta-llama/Llama-2-7b-chat-hf',
            'llama-2-13b-chat': 'meta-llama/Llama-2-13b-chat-hf',
            'llama-2-70b-chat': 'meta-llama/Llama-2-70b-chat-hf',
        }
        
        # Replicate model mappings
        replicate_models = {
            'llama-3.1-8b': 'meta/llama-3.1-8b-instruct',
            'llama-3.1-70b': 'meta/llama-3.1-70b-instruct',
            'llama-3.1-405b': 'meta/llama-3.1-405b-instruct',
            'llama-2-7b': 'meta/llama-2-7b-chat',
            'llama-2-13b': 'meta/llama-2-13b-chat',
            'llama-2-70b': 'meta/llama-2-70b-chat',
        }
        
        # Hugging Face model mappings
        hf_models = {
            'llama-3.1-8b': 'meta-llama/Llama-3.1-8B-Instruct',
            'llama-3.1-70b': 'meta-llama/Llama-3.1-70B-Instruct',
            'llama-3.1-405b': 'meta-llama/Llama-3.1-405B-Instruct',
            'llama-2-7b': 'meta-llama/Llama-2-7b-chat-hf',
            'llama-2-13b': 'meta-llama/Llama-2-13b-chat-hf',
            'llama-2-70b': 'meta-llama/Llama-2-70b-chat-hf',
        }
        
        # Perplexity model mappings
        perplexity_models = {
            'llama-3.1-8b': 'llama-3.1-8b-instruct',
            'llama-3.1-70b': 'llama-3.1-70b-instruct',
            'llama-3.1-405b': 'llama-3.1-405b-instruct',
            'mixtral-8x7b': 'mixtral-8x7b-instruct',
            'codellama-34b': 'codellama-34b-instruct',
        }
        
        if self.api_type == 'together':
            return together_models.get(model, model)
        elif self.api_type == 'replicate':
            return replicate_models.get(model, model)
        elif self.api_type == 'huggingface':
            return hf_models.get(model, model)
        elif self.api_type == 'perplexity':
            return perplexity_models.get(model, model)
        else:
            return model
    
    def generate_text(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate text using Llama model."""
        try:
            model = self.get_model_mapping(model)
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()
            
            # Prepare request data based on API type
            if self.api_type == 'together':
                request_data = self._prepare_together_request(prompt, model, **kwargs)
                url = f"{endpoint}/chat/completions"
            elif self.api_type == 'replicate':
                request_data = self._prepare_replicate_request(prompt, model, **kwargs)
                url = f"{endpoint}/predictions"
            elif self.api_type == 'huggingface':
                request_data = self._prepare_huggingface_request(prompt, model, **kwargs)
                url = f"{endpoint}/models/{model}"
            elif self.api_type == 'perplexity':
                request_data = self._prepare_perplexity_request(prompt, model, **kwargs)
                url = f"{endpoint}/chat/completions"
            else:
                request_data = self._prepare_custom_request(prompt, model, **kwargs)
                url = endpoint
            
            # Make API request
            response = requests.post(url, headers=headers, json=request_data, timeout=60)
            
            if response.status_code == 200:
                response_data = response.json()
                result = self._parse_response(response_data)
                
                # Log successful request
                self.log_request(request_data, response_data, 'success')
                return result
            else:
                error_msg = f"API request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {}, 'error', error_msg)
                raise UserError(_(error_msg))
                
        except Exception as e:
            _logger.error(f"Error in Llama text generation: {str(e)}")
            self.log_request({}, {}, 'error', str(e))
            raise UserError(_('Error generating text with Llama: %s') % str(e))
    
    def chat_completion(self, messages: List[Dict], model: str = None, **kwargs) -> Dict:
        """Generate chat completion using Llama model."""
        try:
            model = self.get_model_mapping(model)
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()
            
            # Prepare request data based on API type
            if self.api_type == 'together':
                request_data = self._prepare_together_chat_request(messages, model, **kwargs)
                url = f"{endpoint}/chat/completions"
            elif self.api_type == 'replicate':
                # Replicate doesn't have native chat, convert to text generation
                prompt = self._messages_to_prompt(messages)
                request_data = self._prepare_replicate_request(prompt, model, **kwargs)
                url = f"{endpoint}/predictions"
            elif self.api_type == 'huggingface':
                prompt = self._messages_to_prompt(messages)
                request_data = self._prepare_huggingface_request(prompt, model, **kwargs)
                url = f"{endpoint}/models/{model}"
            elif self.api_type == 'perplexity':
                request_data = self._prepare_perplexity_chat_request(messages, model, **kwargs)
                url = f"{endpoint}/chat/completions"
            else:
                prompt = self._messages_to_prompt(messages)
                request_data = self._prepare_custom_request(prompt, model, **kwargs)
                url = endpoint
            
            # Make API request
            response = requests.post(url, headers=headers, json=request_data, timeout=60)
            
            if response.status_code == 200:
                response_data = response.json()
                result = self._parse_chat_response(response_data)
                
                # Log successful request
                self.log_request(request_data, response_data, 'success')
                return result
            else:
                error_msg = f"API request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {}, 'error', error_msg)
                raise UserError(_(error_msg))
                
        except Exception as e:
            _logger.error(f"Error in Llama chat completion: {str(e)}")
            self.log_request({}, {}, 'error', str(e))
            raise UserError(_('Error in chat completion with Llama: %s') % str(e))
    
    def get_embeddings(self, text: str, model: str = None) -> List[float]:
        """Get embeddings using Llama model (if supported)."""
        try:
            # Most Llama models don't support embeddings directly
            # Use a compatible embedding model
            embedding_model = model or 'llama-2-7b'  # Fallback model
            
            endpoint = self.get_api_endpoint(embedding_model)
            headers = self.get_headers()
            
            # Prepare embedding request
            if self.api_type == 'together':
                request_data = {
                    'input': text,
                    'model': 'togethercomputer/m2-bert-80M-8k-base'  # Compatible embedding model
                }
                url = f"{endpoint}/embeddings"
            elif self.api_type == 'huggingface':
                request_data = {'inputs': text}
                url = f"{endpoint}/models/sentence-transformers/all-MiniLM-L6-v2"
            else:
                raise UserError(_('Embeddings not supported for this API type'))
            
            # Make API request
            response = requests.post(url, headers=headers, json=request_data, timeout=30)
            
            if response.status_code == 200:
                response_data = response.json()
                embeddings = self._parse_embeddings_response(response_data)
                
                # Log successful request
                self.log_request(request_data, response_data, 'success')
                return embeddings
            else:
                error_msg = f"Embedding request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {}, 'error', error_msg)
                raise UserError(_(error_msg))
                
        except Exception as e:
            _logger.error(f"Error in Llama embeddings: {str(e)}")
            self.log_request({}, {}, 'error', str(e))
            raise UserError(_('Error getting embeddings with Llama: %s') % str(e))
    
    def _prepare_together_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Together AI."""
        return {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_together_chat_request(self, messages: List[Dict], model: str, **kwargs) -> Dict:
        """Prepare chat request data for Together AI."""
        return {
            'model': model,
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_replicate_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Replicate."""
        return {
            'version': model,
            'input': {
                'prompt': prompt,
                'max_tokens': kwargs.get('max_tokens', 1024),
                'temperature': kwargs.get('temperature', 0.7),
                'top_p': kwargs.get('top_p', 1.0),
            }
        }
    
    def _prepare_huggingface_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Hugging Face."""
        return {
            'inputs': prompt,
            'parameters': {
                'max_new_tokens': kwargs.get('max_tokens', 1024),
                'temperature': kwargs.get('temperature', 0.7),
                'top_p': kwargs.get('top_p', 1.0),
                'do_sample': True,
            }
        }
    
    def _prepare_perplexity_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for Perplexity AI."""
        return {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_perplexity_chat_request(self, messages: List[Dict], model: str, **kwargs) -> Dict:
        """Prepare chat request data for Perplexity AI."""
        return {
            'model': model,
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }
    
    def _prepare_custom_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare request data for custom API."""
        return {
            'model': model,
            'prompt': prompt,
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
        }
    
    def _parse_response(self, response_data: Dict) -> str:
        """Parse response data and extract generated text."""
        if self.api_type == 'together':
            return response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
        elif self.api_type == 'replicate':
            return response_data.get('output', [''])[0] if response_data.get('output') else ''
        elif self.api_type == 'huggingface':
            return response_data[0].get('generated_text', '') if response_data else ''
        elif self.api_type == 'perplexity':
            return response_data.get('choices', [{}])[0].get('message', {}).get('content', '')
        else:
            return response_data.get('text', '') or response_data.get('content', '')
    
    def _parse_chat_response(self, response_data: Dict) -> Dict:
        """Parse chat response data."""
        if self.api_type == 'together':
            return {
                'content': response_data.get('choices', [{}])[0].get('message', {}).get('content', ''),
                'role': 'assistant',
                'model': response_data.get('model', ''),
                'usage': response_data.get('usage', {}),
            }
        elif self.api_type == 'replicate':
            content = response_data.get('output', [''])[0] if response_data.get('output') else ''
            return {
                'content': content,
                'role': 'assistant',
                'model': response_data.get('model', ''),
                'usage': {},
            }
        elif self.api_type == 'perplexity':
            return {
                'content': response_data.get('choices', [{}])[0].get('message', {}).get('content', ''),
                'role': 'assistant',
                'model': response_data.get('model', ''),
                'usage': response_data.get('usage', {}),
            }
        else:
            return {
                'content': response_data.get('text', '') or response_data.get('content', ''),
                'role': 'assistant',
                'model': response_data.get('model', ''),
                'usage': response_data.get('usage', {}),
            }
    
    def _parse_embeddings_response(self, response_data: Dict) -> List[float]:
        """Parse embeddings response data."""
        if self.api_type == 'together':
            return response_data.get('data', [{}])[0].get('embedding', [])
        elif self.api_type == 'huggingface':
            return response_data[0] if response_data else []
        else:
            return response_data.get('embedding', [])
    
    def _messages_to_prompt(self, messages: List[Dict]) -> str:
        """Convert chat messages to a single prompt string."""
        prompt = ""
        for message in messages:
            role = message.get('role', 'user')
            content = message.get('content', '')
            
            if role == 'system':
                prompt += f"System: {content}\n\n"
            elif role == 'user':
                prompt += f"User: {content}\n\n"
            elif role == 'assistant':
                prompt += f"Assistant: {content}\n\n"
        
        prompt += "Assistant: "
        return prompt
    
    def test_connection(self) -> bool:
        """Test the connection to the Llama API."""
        try:
            # Simple test with a short prompt
            test_prompt = "Hello, this is a test message. Please respond with 'OK'."
            result = self.generate_text(test_prompt, max_tokens=10)
            
            if result and len(result.strip()) > 0:
                _logger.info(f"Llama API connection test successful: {result[:50]}...")
                return True
            else:
                _logger.warning("Llama API connection test failed: Empty response")
                return False
                
        except Exception as e:
            _logger.error(f"Llama API connection test failed: {str(e)}")
            return False
    
    def get_available_models(self) -> List[Dict]:
        """Get list of available Llama models for this API type."""
        if self.api_type == 'together':
            return [
                {'code': 'llama-3.1-8b', 'name': 'Llama 3.1 8B', 'context_length': 8192},
                {'code': 'llama-3.1-70b', 'name': 'Llama 3.1 70B', 'context_length': 8192},
                {'code': 'llama-3.1-405b', 'name': 'Llama 3.1 405B', 'context_length': 8192},
                {'code': 'llama-2-7b', 'name': 'Llama 2 7B', 'context_length': 4096},
                {'code': 'llama-2-13b', 'name': 'Llama 2 13B', 'context_length': 4096},
                {'code': 'llama-2-70b', 'name': 'Llama 2 70B', 'context_length': 4096},
            ]
        elif self.api_type == 'replicate':
            return [
                {'code': 'llama-3.1-8b', 'name': 'Llama 3.1 8B', 'context_length': 8192},
                {'code': 'llama-3.1-70b', 'name': 'Llama 3.1 70B', 'context_length': 8192},
                {'code': 'llama-3.1-405b', 'name': 'Llama 3.1 405B', 'context_length': 8192},
                {'code': 'llama-2-7b', 'name': 'Llama 2 7B', 'context_length': 4096},
                {'code': 'llama-2-13b', 'name': 'Llama 2 13B', 'context_length': 4096},
                {'code': 'llama-2-70b', 'name': 'Llama 2 70B', 'context_length': 4096},
            ]
        elif self.api_type == 'perplexity':
            return [
                {'code': 'llama-3.1-8b', 'name': 'Llama 3.1 8B', 'context_length': 8192},
                {'code': 'llama-3.1-70b', 'name': 'Llama 3.1 70B', 'context_length': 8192},
                {'code': 'llama-3.1-405b', 'name': 'Llama 3.1 405B', 'context_length': 8192},
                {'code': 'mixtral-8x7b', 'name': 'Mixtral 8x7B', 'context_length': 32768},
                {'code': 'codellama-34b', 'name': 'Code Llama 34B', 'context_length': 16384},
            ]
        else:
            return [
                {'code': 'llama-3.1-8b', 'name': 'Llama 3.1 8B', 'context_length': 8192},
                {'code': 'llama-3.1-70b', 'name': 'Llama 3.1 70B', 'context_length': 8192},
                {'code': 'llama-2-7b', 'name': 'Llama 2 7B', 'context_length': 4096},
                {'code': 'llama-2-13b', 'name': 'Llama 2 13B', 'context_length': 4096},
                {'code': 'llama-2-70b', 'name': 'Llama 2 70B', 'context_length': 4096},
            ] 