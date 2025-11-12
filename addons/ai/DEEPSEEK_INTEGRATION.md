# DeepSeek Integration for AI Automation Base

## Overview

The AI Automation Base module now includes comprehensive support for DeepSeek AI models through multiple API providers. This integration allows you to leverage the power of DeepSeek models for text generation, chat completion, code generation, and mathematical reasoning within your Odoo system.

## Supported API Providers

### 1. DeepSeek AI (Official)
- **URL**: https://platform.deepseek.com
- **Models**: All DeepSeek models (Chat, Coder, Math series)
- **Features**: Chat completion, text generation, streaming
- **Cost**: Competitive pricing with generous free tier
- **Recommended for**: Production use, direct API access

### 2. Together AI
- **URL**: https://together.ai
- **Models**: DeepSeek models via their platform
- **Features**: Chat completion, text generation, embeddings
- **Cost**: Very competitive pricing
- **Recommended for**: Production use, high-volume applications

### 3. Replicate
- **URL**: https://replicate.com
- **Models**: DeepSeek models via their platform
- **Features**: Text generation (chat via prompt conversion)
- **Cost**: Pay-per-use model
- **Recommended for**: Development, prototyping

### 4. Hugging Face
- **URL**: https://huggingface.co
- **Models**: DeepSeek models via Inference API
- **Features**: Text generation, embeddings
- **Cost**: Free tier available, paid plans for production
- **Recommended for**: Research, development

### 5. Custom API
- **URL**: Configurable
- **Models**: Any DeepSeek-compatible model
- **Features**: Full customization
- **Cost**: Depends on provider
- **Recommended for**: Enterprise deployments

## Available Models

### DeepSeek Chat Series
- **DeepSeek Chat**: General purpose chat model with 32K context window
- **DeepSeek LLM 7B Chat**: 7B parameter chat model for general conversation
- **DeepSeek LLM 67B Chat**: 67B parameter chat model for complex reasoning

### DeepSeek Coder Series
- **DeepSeek Coder**: Specialized for code generation and programming tasks
- **DeepSeek Coder Instruct**: Instruction-tuned version for code generation
- **DeepSeek Coder 33B Instruct**: Large instruction-tuned model for complex coding tasks
- **DeepSeek Coder 6.7B Instruct**: Medium-sized model for code generation
- **DeepSeek Coder 1.3B Instruct**: Small, fast model for basic code generation

### DeepSeek Math Series
- **DeepSeek Math 7B Instruct**: Specialized for mathematical reasoning and problem solving
- **DeepSeek Math 67B Instruct**: Large model specialized for advanced mathematics

## Setup Instructions

### 1. API Provider Setup

#### DeepSeek AI (Official)
1. Visit https://platform.deepseek.com and create an account
2. Navigate to API Keys section
3. Generate a new API key
4. Copy the API key for use in Odoo

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

### 2. Odoo Configuration

#### Step 1: Create API Key
1. Go to **AI Automation > Security > API Keys**
2. Click **Create**
3. Enter a name (e.g., "DeepSeek AI Key")
4. Paste your API key
5. Save the record

#### Step 2: Configure Provider
1. Go to **AI Automation > Configuration > LLM Providers**
2. Click **Create**
3. Fill in the details:
   - **Name**: "DeepSeek AI" (or your preferred name)
   - **Code**: "deepseek"
   - **API Base URL**: "https://api.deepseek.com/v1" (for DeepSeek AI)
   - **Default Model**: Select "DeepSeek Chat"
   - **API Key**: Select the API key created in Step 1
4. Save the record

#### Step 3: Configure DeepSeek Service
1. Go to **AI Automation > Configuration > DeepSeek Services**
2. Click **Create**
3. Select the appropriate **API Type** (e.g., "DeepSeek AI")
4. If using custom API, enter the **Custom API URL**
5. Save the record

## Usage Examples

### Text Generation
```python
# Get DeepSeek service
deepseek_service = env['llm.deepseek.service']

# Generate text
response = deepseek_service.generate_text(
    prompt="Explain quantum computing in simple terms",
    model="deepseek-chat",
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
response = deepseek_service.chat_completion(
    messages=messages,
    model="deepseek-chat",
    max_tokens=200
)
print(response['content'])
```

### Code Generation
```python
# Generate Python code
code_prompt = "Write a Python function to calculate the factorial of a number"
response = deepseek_service.generate_text(
    prompt=code_prompt,
    model="deepseek-coder",
    max_tokens=300,
    temperature=0.3
)
print(response)
```

### Mathematical Reasoning
```python
# Solve a math problem
math_prompt = "Solve the equation: 2x + 5 = 13"
response = deepseek_service.generate_text(
    prompt=math_prompt,
    model="deepseek-math-7b-instruct",
    max_tokens=200,
    temperature=0.1
)
print(response)
```

## Model Capabilities

| Model | Chat | Text Generation | Code Generation | Math Reasoning | Streaming | Context Length |
|-------|------|----------------|----------------|----------------|-----------|----------------|
| DeepSeek Chat | ✅ | ✅ | ✅ | ✅ | ✅ | 32,768 |
| DeepSeek Coder | ✅ | ✅ | ✅ | ✅ | ✅ | 16,384 |
| DeepSeek Coder Instruct | ✅ | ✅ | ✅ | ✅ | ✅ | 16,384 |
| DeepSeek Coder 33B Instruct | ✅ | ✅ | ✅ | ✅ | ✅ | 16,384 |
| DeepSeek Coder 6.7B Instruct | ✅ | ✅ | ✅ | ✅ | ✅ | 16,384 |
| DeepSeek Coder 1.3B Instruct | ✅ | ✅ | ✅ | ✅ | ✅ | 16,384 |
| DeepSeek LLM 7B Chat | ✅ | ✅ | ✅ | ✅ | ✅ | 32,768 |
| DeepSeek LLM 67B Chat | ✅ | ✅ | ✅ | ✅ | ✅ | 32,768 |
| DeepSeek Math 7B Instruct | ✅ | ✅ | ✅ | ✅ | ✅ | 32,768 |
| DeepSeek Math 67B Instruct | ✅ | ✅ | ✅ | ✅ | ✅ | 32,768 |

## Cost Considerations

### DeepSeek AI Pricing (approximate)
- **DeepSeek Chat**: $0.00014 per 1K input tokens, $0.00028 per 1K output tokens
- **DeepSeek Coder**: $0.00014 per 1K input tokens, $0.00028 per 1K output tokens
- **DeepSeek Coder 33B Instruct**: $0.0007 per 1K input tokens, $0.0014 per 1K output tokens
- **DeepSeek LLM 7B Chat**: $0.00007 per 1K input tokens, $0.00014 per 1K output tokens
- **DeepSeek LLM 67B Chat**: $0.0007 per 1K input tokens, $0.0014 per 1K output tokens
- **DeepSeek Math 7B Instruct**: $0.00007 per 1K input tokens, $0.00014 per 1K output tokens
- **DeepSeek Math 67B Instruct**: $0.0007 per 1K input tokens, $0.0014 per 1K output tokens

### Together AI Pricing (approximate)
- **DeepSeek models**: Competitive pricing similar to official API
- **Additional features**: Embeddings support, custom deployments

### Replicate Pricing (approximate)
- **DeepSeek models**: Pay-per-use model
- **Cost-effective**: For development and prototyping

## Best Practices

### 1. Model Selection
- **For general conversation**: Use DeepSeek Chat or DeepSeek LLM 7B Chat
- **For code generation**: Use DeepSeek Coder or DeepSeek Coder Instruct
- **For complex coding**: Use DeepSeek Coder 33B Instruct
- **For mathematical reasoning**: Use DeepSeek Math 7B Instruct or DeepSeek Math 67B Instruct
- **For cost optimization**: Use smaller models (7B) for basic tasks

### 2. API Provider Selection
- **Production use**: DeepSeek AI (official) or Together AI
- **Development**: Hugging Face (free tier) or Replicate
- **Enterprise**: Custom API deployment

### 3. Cost Optimization
- Use smaller models for simple tasks
- Implement caching for repeated requests
- Monitor usage through request logs
- Set appropriate token limits
- Use streaming for long responses

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

For technical support or questions about the DeepSeek integration:

- **Email**: info@ecosire.com
- **Website**: https://www.ecosire.com
- **Documentation**: Check the module documentation for detailed API references

## Changelog

### Version 1.0.0
- Initial DeepSeek integration
- Support for DeepSeek AI, Together AI, Replicate, and Hugging Face
- Complete model coverage for Chat, Coder, and Math series
- Comprehensive test suite
- Full UI integration with Odoo

---

**Developed by ECOSIRE (PRIVATE) LIMITED**
- **Website**: https://www.ecosire.com
- **Email**: info@ecosire.com
- **Official Number**: 0923130168262 