# Meta Llama Integration for AI Automation Base

## Overview

The AI Automation Base module now includes comprehensive support for Meta Llama models through multiple API providers. This integration allows you to leverage the power of Llama models for text generation, chat completion, and other AI tasks within your Odoo system.

## Supported API Providers

### 1. Together AI
- **URL**: https://together.ai
- **Models**: All Llama 3.1 and Llama 2 models
- **Features**: Chat completion, text generation, embeddings
- **Cost**: Very competitive pricing
- **Recommended for**: Production use, high-volume applications

### 2. Replicate
- **URL**: https://replicate.com
- **Models**: Llama 3.1 and Llama 2 models
- **Features**: Text generation (chat via prompt conversion)
- **Cost**: Pay-per-use model
- **Recommended for**: Development, prototyping

### 3. Hugging Face
- **URL**: https://huggingface.co
- **Models**: All Llama models via Inference API
- **Features**: Text generation, embeddings
- **Cost**: Free tier available, paid plans for production
- **Recommended for**: Research, development

### 4. Perplexity AI
- **URL**: https://perplexity.ai
- **Models**: Llama 3.1, Mixtral, Code Llama
- **Features**: Chat completion, text generation
- **Cost**: Competitive pricing
- **Recommended for**: Production use

### 5. Custom API
- **URL**: Configurable
- **Models**: Any Llama-compatible model
- **Features**: Full customization
- **Cost**: Depends on provider
- **Recommended for**: Enterprise deployments

## Available Models

### Llama 3.1 Series
- **Llama 3.1 8B**: Fast and cost-effective for basic tasks
- **Llama 3.1 70B**: Balanced performance for complex reasoning
- **Llama 3.1 405B**: Most capable model for advanced tasks

### Llama 2 Series
- **Llama 2 7B**: Cost-effective for basic text generation
- **Llama 2 13B**: Good balance of performance and cost
- **Llama 2 70B**: High-quality responses for complex tasks

### Specialized Models
- **Mixtral 8x7B**: High-performance mixture-of-experts model
- **Code Llama 34B**: Specialized for code generation tasks

## Setup Instructions

### 1. API Provider Setup

#### Together AI
1. Visit https://together.ai and create an account
2. Navigate to API Keys section
3. Generate a new API key
4. Copy the API key for use in Odoo

#### Replicate
1. Visit https://replicate.com and create an account
2. Go to Account Settings > API Tokens
3. Generate a new API token
4. Copy the token for use in Odoo

#### Hugging Face
1. Visit https://huggingface.co and create an account
2. Go to Settings > Access Tokens
3. Create a new token with read permissions
4. Copy the token for use in Odoo

#### Perplexity AI
1. Visit https://perplexity.ai and create an account
2. Navigate to API section
3. Generate an API key
4. Copy the key for use in Odoo

### 2. Odoo Configuration

#### Step 1: Create API Key
1. Go to **AI Automation > Security > API Keys**
2. Click **Create**
3. Enter a name (e.g., "Together AI Llama Key")
4. Paste your API key
5. Save the record

#### Step 2: Configure Provider
1. Go to **AI Automation > Configuration > LLM Providers**
2. Click **Create**
3. Fill in the details:
   - **Name**: "Together AI Llama" (or your preferred name)
   - **Code**: "llama"
   - **API Base URL**: "https://api.together.xyz/v1" (for Together AI)
   - **Default Model**: Select "Llama 3.1 8B"
   - **API Key**: Select the API key created in Step 1
4. Save the record

#### Step 3: Configure Llama Service
1. Go to **AI Automation > Configuration > Meta Llama Services**
2. Click **Create**
3. Select the appropriate **API Type** (e.g., "Together AI")
4. If using custom API, enter the **Custom API URL**
5. Save the record

## Usage Examples

### Text Generation
```python
# Get Llama service
llama_service = env['llm.llama.service']

# Generate text
response = llama_service.generate_text(
    prompt="Explain quantum computing in simple terms",
    model="llama-3.1-8b",
    max_tokens=500,
    temperature=0.7
)
print(response)
```

### Chat Completion
```python
# Prepare chat messages
messages = [
    {'role': 'system', 'content': 'You are a helpful assistant.'},
    {'role': 'user', 'content': 'What is the capital of France?'}
]

# Get chat completion
response = llama_service.chat_completion(
    messages=messages,
    model="llama-3.1-70b",
    max_tokens=200
)
print(response['content'])
```

### Embeddings (if supported)
```python
# Get embeddings
embeddings = llama_service.get_embeddings(
    text="This is a sample text for embedding",
    model="llama-3.1-8b"
)
print(f"Embedding dimensions: {len(embeddings)}")
```

## Model Capabilities

| Model | Chat | Text Generation | Embeddings | Streaming | Function Calling | Context Length |
|-------|------|----------------|------------|-----------|------------------|----------------|
| Llama 3.1 8B | ✅ | ✅ | ❌ | ✅ | ❌ | 8,192 |
| Llama 3.1 70B | ✅ | ✅ | ❌ | ✅ | ❌ | 8,192 |
| Llama 3.1 405B | ✅ | ✅ | ❌ | ✅ | ❌ | 8,192 |
| Llama 2 7B | ✅ | ✅ | ❌ | ✅ | ❌ | 4,096 |
| Llama 2 13B | ✅ | ✅ | ❌ | ✅ | ❌ | 4,096 |
| Llama 2 70B | ✅ | ✅ | ❌ | ✅ | ❌ | 4,096 |
| Mixtral 8x7B | ✅ | ✅ | ❌ | ✅ | ❌ | 32,768 |
| Code Llama 34B | ✅ | ✅ | ❌ | ✅ | ❌ | 16,384 |

## Cost Considerations

### Together AI Pricing (approximate)
- **Llama 3.1 8B**: $0.0002 per 1K tokens
- **Llama 3.1 70B**: $0.0007 per 1K tokens
- **Llama 3.1 405B**: $0.0024 per 1K tokens

### Replicate Pricing (approximate)
- **Llama 3.1 8B**: $0.0002 per 1K tokens
- **Llama 3.1 70B**: $0.0007 per 1K tokens

### Perplexity AI Pricing (approximate)
- **Llama 3.1 8B**: $0.0002 per 1K tokens
- **Mixtral 8x7B**: $0.00014 per 1K tokens

## Best Practices

### 1. Model Selection
- **For basic tasks**: Use Llama 3.1 8B or Llama 2 7B
- **For complex reasoning**: Use Llama 3.1 70B or 405B
- **For code generation**: Use Code Llama 34B
- **For high-performance**: Use Mixtral 8x7B

### 2. API Provider Selection
- **Production use**: Together AI or Perplexity AI
- **Development**: Hugging Face (free tier)
- **Enterprise**: Custom API deployment

### 3. Cost Optimization
- Use smaller models for simple tasks
- Implement caching for repeated requests
- Monitor usage through request logs
- Set appropriate token limits

### 4. Error Handling
- Implement retry logic for rate limits
- Handle API timeouts gracefully
- Log errors for debugging
- Provide fallback responses

## Troubleshooting

### Common Issues

#### 1. API Key Errors
**Problem**: "Invalid API key" or "Unauthorized"
**Solution**: 
- Verify API key is correct
- Check if API key has proper permissions
- Ensure API key is active in the provider

#### 2. Model Not Found
**Problem**: "Model not available" or "Model not found"
**Solution**:
- Verify model name is correct
- Check if model is available for your API provider
- Ensure model is active in the system

#### 3. Rate Limiting
**Problem**: "Rate limit exceeded" or "Too many requests"
**Solution**:
- Implement exponential backoff
- Reduce request frequency
- Upgrade API plan if needed

#### 4. Timeout Errors
**Problem**: "Request timeout" or "Connection error"
**Solution**:
- Increase timeout settings
- Check network connectivity
- Try a different API provider

### Debugging Tips

1. **Enable Debug Logging**: Check Odoo logs for detailed error messages
2. **Test Connection**: Use the "Test Connection" button in the service configuration
3. **Monitor Request Logs**: Check AI Automation > Monitoring > Request Logs
4. **Verify API Status**: Check provider's status page for service issues

## Security Considerations

1. **API Key Protection**: Store API keys securely using Odoo's encryption
2. **Access Control**: Use appropriate user groups for service access
3. **Request Logging**: Monitor all API requests for security
4. **Data Privacy**: Ensure compliance with data protection regulations

## Support

For technical support or questions about the Meta Llama integration:

- **Email**: info@ecosire.com
- **Website**: https://www.ecosire.com
- **Documentation**: Check the module documentation for detailed API references

## Changelog

### Version 1.0.0
- Initial Meta Llama integration
- Support for Together AI, Replicate, Hugging Face, and Perplexity AI
- Complete model coverage for Llama 3.1 and Llama 2 series
- Comprehensive test suite
- Full UI integration with Odoo

---

**Developed by ECOSIRE (PRIVATE) LIMITED**
- **Website**: https://www.ecosire.com
- **Email**: info@ecosire.com
- **Official Number**: 0923130168262 