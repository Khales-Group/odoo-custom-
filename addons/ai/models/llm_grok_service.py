from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import json
import logging
import requests
from typing import Dict, List, Optional, Any, Union
import time

_logger = logging.getLogger(__name__)


class LLMGrokService(models.Model):
    """Service implementation for xAI Grok models."""

    _name = 'llm.grok.service'
    _description = 'xAI Grok Service'
    _inherit = 'llm.base.service'

    # Grok-specific configuration
    api_version = fields.Selection([
        ('v1', 'API v1'),
    ], string='API Version', required=True, default='v1',
       help='Grok API version to use')

    def get_api_endpoint(self, model: str = None) -> str:
        """Get the Grok API endpoint."""
        return 'https://api.x.ai/v1'

    def get_headers(self) -> Dict[str, str]:
        """Get headers for Grok API requests."""
        api_key = self.get_api_key()
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'Odoo-AI-Automation/1.0',
        }
        return headers

    def get_model_mapping(self, model: str = None) -> str:
        """Map Odoo model codes to Grok model names."""
        if not model:
            model = self.get_default_model()

        # Grok model mappings
        grok_models = {
            'grok-beta': 'grok-beta',
            'grok-2': 'grok-2',
            'grok-2-mini': 'grok-2-mini',
            'grok-2-vision': 'grok-2-vision',
            'grok-2-vision-mini': 'grok-2-vision-mini',
        }

        return grok_models.get(model, model)

    def generate_text(self, prompt: str, model: str = None, **kwargs) -> str:
        """Generate text using Grok model."""
        try:
            model = self.get_model_mapping(model)
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()

            # Prepare request data
            request_data = self._prepare_text_request(prompt, model, **kwargs)
            url = f"{endpoint}/chat/completions"

            # Make API request
            response = requests.post(url, headers=headers, json=request_data, timeout=60)

            if response.status_code == 200:
                response_data = response.json()
                result = self._parse_text_response(response_data)

                # Log successful request
                self.log_request(request_data, response_data, 'success')
                return result
            else:
                error_msg = f"Grok API request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {}, 'error', error_msg)
                raise UserError(_(error_msg))

        except Exception as e:
            _logger.error(f"Error in Grok text generation: {str(e)}")
            self.log_request({}, {}, 'error', str(e))
            raise UserError(_('Error generating text with Grok: %s') % str(e))

    def chat_completion(self, messages: List[Dict], model: str = None, **kwargs) -> Dict:
        """Generate chat completion using Grok model."""
        try:
            model = self.get_model_mapping(model)
            endpoint = self.get_api_endpoint(model)
            headers = self.get_headers()

            # Prepare request data
            request_data = self._prepare_chat_request(messages, model, **kwargs)
            url = f"{endpoint}/chat/completions"

            # Make API request
            response = requests.post(url, headers=headers, json=request_data, timeout=60)

            if response.status_code == 200:
                response_data = response.json()
                result = self._parse_chat_response(response_data)

                # Log successful request
                self.log_request(request_data, response_data, 'success')
                return result
            else:
                error_msg = f"Grok API request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {}, 'error', error_msg)
                raise UserError(_(error_msg))

        except Exception as e:
            _logger.error(f"Error in Grok chat completion: {str(e)}")
            self.log_request({}, {}, 'error', str(e))
            raise UserError(_('Error in chat completion with Grok: %s') % str(e))

    def get_embeddings(self, text: str, model: str = None) -> List[float]:
        """Get embeddings using Grok model."""
        try:
            # Grok doesn't have dedicated embedding models, use text-embedding-3-small as fallback
            embedding_model = 'text-embedding-3-small'
            endpoint = self.get_api_endpoint(embedding_model)
            headers = self.get_headers()

            # Prepare embedding request
            request_data = {
                'input': text,
                'model': embedding_model,
            }
            url = f"{endpoint}/embeddings"

            # Make API request
            response = requests.post(url, headers=headers, json=request_data, timeout=30)

            if response.status_code == 200:
                response_data = response.json()
                embeddings = self._parse_embeddings_response(response_data)

                # Log successful request
                self.log_request(request_data, response_data, 'success')
                return embeddings
            else:
                error_msg = f"Grok embedding request failed: {response.status_code} - {response.text}"
                self.log_request(request_data, {}, 'error', error_msg)
                raise UserError(_(error_msg))

        except Exception as e:
            _logger.error(f"Error in Grok embeddings: {str(e)}")
            self.log_request({}, {}, 'error', str(e))
            raise UserError(_('Error getting embeddings with Grok: %s') % str(e))

    def _prepare_text_request(self, prompt: str, model: str, **kwargs) -> Dict:
        """Prepare text generation request data for Grok."""
        return {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }

    def _prepare_chat_request(self, messages: List[Dict], model: str, **kwargs) -> Dict:
        """Prepare chat completion request data for Grok."""
        return {
            'model': model,
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
            'top_p': kwargs.get('top_p', 1.0),
            'stream': kwargs.get('stream', False),
        }

    def _parse_text_response(self, response_data: Dict) -> str:
        """Parse text generation response data and extract generated text."""
        return response_data.get('choices', [{}])[0].get('message', {}).get('content', '')

    def _parse_chat_response(self, response_data: Dict) -> Dict:
        """Parse chat response data."""
        return {
            'content': response_data.get('choices', [{}])[0].get('message', {}).get('content', ''),
            'role': 'assistant',
            'model': response_data.get('model', ''),
            'usage': response_data.get('usage', {}),
        }

    def _parse_embeddings_response(self, response_data: Dict) -> List[float]:
        """Parse embeddings response data."""
        return response_data.get('data', [{}])[0].get('embedding', [])

    def test_connection(self) -> bool:
        """Test the connection to the Grok API."""
        try:
            # Simple test with a short prompt
            test_prompt = "Hello, this is a test message. Please respond with 'OK'."
            result = self.generate_text(test_prompt, max_tokens=10)

            if result and len(result.strip()) > 0:
                _logger.info(f"Grok API connection test successful: {result[:50]}...")
                return True
            else:
                _logger.warning("Grok API connection test failed: Empty response")
                return False

        except Exception as e:
            _logger.error(f"Grok API connection test failed: {str(e)}")
            return False

    def get_available_models(self) -> List[Dict]:
        """Get list of available Grok models."""
        return [
            {'code': 'grok-beta', 'name': 'Grok Beta', 'context_length': 8192},
            {'code': 'grok-2', 'name': 'Grok 2', 'context_length': 32768},
            {'code': 'grok-2-mini', 'name': 'Grok 2 Mini', 'context_length': 16384},
            {'code': 'grok-2-vision', 'name': 'Grok 2 Vision', 'context_length': 32768},
            {'code': 'grok-2-vision-mini', 'name': 'Grok 2 Vision Mini', 'context_length': 16384},
        ] 