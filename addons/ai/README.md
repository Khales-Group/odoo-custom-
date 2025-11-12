# 🤖 AI Automation Base

**The Ultimate Foundation for AI-Powered Odoo Applications**

[![Odoo Version](https://img.shields.io/badge/Odoo-18.0+-green.svg)](https://www.odoo.com)
[![License](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0.html)
[![Python](https://img.shields.io/badge/Python-3.8+-yellow.svg)](https://www.python.org)
[![Security](https://img.shields.io/badge/Security-Enterprise%20Grade-red.svg)](https://www.ecosire.com)

## 🚀 Overview

AI Automation Base is a comprehensive, enterprise-grade Odoo module that provides a secure, scalable, and extensible foundation for integrating Large Language Models (LLMs) into your Odoo ecosystem. Built with modern architecture and security best practices, it enables seamless AI automation across all your business processes.

### 🌟 Key Highlights

- **🔐 Enterprise Security**: Secure API key management with encryption
- **🔄 Provider Agnostic**: Support for OpenAI, Google Gemini, and Anthropic Claude
- **⚡ High Performance**: Intelligent rate limiting and caching
- **📊 Comprehensive Monitoring**: Real-time analytics and usage tracking
- **🎨 Modern UI**: Responsive design with dark mode support
- **🛠️ Extensible**: Framework for custom AI tools and functions

## 🎯 Features

### Core AI Capabilities

| Feature | Description | Supported Providers |
|---------|-------------|-------------------|
| **Text Generation** | Generate high-quality content for emails, reports, and documentation | OpenAI, Gemini, Claude |
| **Chat Completion** | Build conversational AI interfaces with context-aware responses | OpenAI, Gemini, Claude |
| **Embeddings** | Convert text to vector representations for semantic search | OpenAI, Gemini, Claude |
| **Streaming Responses** | Real-time AI responses for interactive user experiences | OpenAI, Gemini, Claude |
| **Function Calling** | Enable AI to execute actions within your Odoo system | OpenAI, Gemini, Claude |

### Security & Management

- **🔐 Secure API Key Storage**: All API keys encrypted and stored securely
- **👥 Role-Based Access Control**: Granular permissions for AI User, Manager, and Admin roles
- **📝 Audit Logging**: Comprehensive logging of all AI interactions
- **🛡️ Input Validation**: Sanitization and validation of all AI inputs
- **🔒 HTTPS Communication**: Encrypted data transmission

### Performance & Scalability

- **⚡ Intelligent Rate Limiting**: Proactive monitoring and management of API quotas
- **🔄 Asynchronous Processing**: Non-blocking AI operations for better UX
- **💾 Smart Caching**: Reduce redundant API calls and costs
- **📊 Performance Analytics**: Monitor response times and success rates
- **🔄 Load Balancing**: Automatic failover between providers

## 🏗️ Architecture

### Modular Design

```
ai_automation_base/
├── models/                    # Data models and business logic
│   ├── llm_provider.py       # Provider configurations
│   ├── llm_api_key.py        # Secure API key management
│   ├── llm_provider_model.py # Model capabilities and pricing
│   ├── llm_base_service.py   # Abstract base service
│   ├── llm_openai_service.py # OpenAI implementation
│   ├── llm_gemini_service.py # Google Gemini implementation
│   ├── llm_claude_service.py # Anthropic Claude implementation
│   └── llm_request_log.py    # Request/response logging
├── controllers/              # REST API endpoints
├── views/                    # Odoo UI components
├── security/                 # Access control and permissions
├── data/                     # Default configurations
└── static/                   # Frontend assets
```

### Provider-Agnostic Interface

The module uses an abstract base service (`llm.base.service`) that provides a unified interface for all LLM providers. This design ensures:

- **No Vendor Lock-in**: Easy switching between providers
- **Consistent API**: Same methods across all providers
- **Extensible**: Simple to add new providers
- **Configurable**: Dynamic provider selection based on requirements

## 🚀 Quick Start

### 1. Installation

```bash
# Clone or download the module
# Place in your Odoo addons directory
# Install via Odoo Apps menu
```

### 2. Configuration

1. **Install the Module**: Go to Apps → Search "AI Automation Base" → Install
2. **Configure API Keys**: 
   - Navigate to AI Automation → API Keys
   - Add your OpenAI, Gemini, and Claude API keys
   - Keys are encrypted and stored securely
3. **Set Up Providers**:
   - Go to AI Automation → Providers
   - Configure each LLM provider with base URLs and default models
4. **Assign Permissions**:
   - Users → Groups → AI User/Manager/Admin
   - Assign appropriate roles to users

### 3. Basic Usage

#### Python API Usage

```python
# Get the LLM service
llm_service = self.env['llm.base.service']

# Generate text
response = llm_service.generate_text(
    prompt="Write a professional email introduction",
    provider="openai",
    model="gpt-4o",
    temperature=0.7
)

# Chat completion
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain AI automation in simple terms."}
]
response = llm_service.chat_completion(
    messages=messages,
    provider="claude",
    model="claude-3-sonnet-20240229"
)

# Get embeddings
embeddings = llm_service.get_embeddings(
    text="Sample text for embedding",
    provider="openai",
    model="text-embedding-3-small"
)
```

#### JavaScript Frontend Usage

```javascript
// Load the LLM service
var LLMService = require('ai_automation_base.llm_service');

// Generate text
LLMService.generateText(
    "Write a sales pitch for our new product",
    "openai",
    "gpt-4o",
    {temperature: 0.8}
).then(function(response) {
    console.log("Generated text:", response);
});

// Streaming response
LLMService.streamResponse(
    "Tell me a story",
    "claude",
    "claude-3-sonnet-20240229",
    {},
    function(chunk) {
        // Handle each chunk
        console.log("Received chunk:", chunk);
    },
    function() {
        // Handle completion
        console.log("Streaming completed");
    },
    function(error) {
        // Handle errors
        console.error("Error:", error);
    }
);
```

#### REST API Usage

```bash
# Generate text
curl -X POST "http://your-odoo.com/ai_automation/llm/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "prompt": "Write a professional email",
    "provider": "openai",
    "model": "gpt-4o",
    "temperature": 0.7
  }'

# Chat completion
curl -X POST "http://your-odoo.com/ai_automation/llm/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ],
    "provider": "claude",
    "model": "claude-3-sonnet-20240229"
  }'
```

## 🔧 Advanced Features

### Function Calling Framework

Enable AI to execute actions within your Odoo system:

```python
# Define custom functions
def get_stock_quantity(self, product_name):
    """Get current stock quantity for a product"""
    product = self.env['product.product'].search([('name', '=', product_name)], limit=1)
    return product.qty_available if product else 0

# Register with LLM service
llm_service.register_function(
    name="get_stock_quantity",
    description="Get current stock quantity for a product",
    function=get_stock_quantity,
    parameters={
        "type": "object",
        "properties": {
            "product_name": {"type": "string", "description": "Name of the product"}
        },
        "required": ["product_name"]
    }
)
```

### Custom Provider Integration

Add new LLM providers easily:

```python
class LLMCustomService(models.AbstractModel):
    _inherit = 'llm.base.service'
    _name = 'llm.custom.service'
    
    def generate_text(self, prompt, model=None, **kwargs):
        """Implement custom provider logic"""
        # Your custom implementation here
        pass
    
    def chat_completion(self, messages, model=None, **kwargs):
        """Implement custom chat completion"""
        # Your custom implementation here
        pass
```

### Automated Actions Integration

Use AI in Odoo automated actions:

```python
# In automated action
def ai_generate_description(self):
    """Generate product description using AI"""
    llm_service = self.env['llm.base.service']
    
    prompt = f"Generate a compelling product description for: {self.name}"
    description = llm_service.generate_text(
        prompt=prompt,
        provider="openai",
        model="gpt-4o",
        temperature=0.7
    )
    
    self.write({'description': description})
```

## 📊 Monitoring & Analytics

### Dashboard Features

- **Real-time Usage**: Monitor API calls and costs
- **Performance Metrics**: Response times and success rates
- **Provider Analytics**: Usage breakdown by provider
- **Cost Tracking**: Monthly and per-request cost analysis
- **Error Monitoring**: Failed requests and error patterns

### Request Logs

Comprehensive logging includes:
- Request/response data
- Token usage and costs
- Response times
- Error details
- User information
- Provider and model used

## 🔒 Security Features

### API Key Management

- **Encrypted Storage**: All API keys encrypted and stored securely
- **Access Control**: Only authorized users can view/modify keys
- **Usage Tracking**: Monitor key usage and rotation
- **Secure Transmission**: HTTPS for all API communications

### Access Control

Three security levels:
- **AI User**: Can use AI features
- **AI Manager**: Can configure providers and view logs
- **AI Admin**: Full access including API key management

### Data Protection

- **Input Sanitization**: All user inputs validated and sanitized
- **Audit Trail**: Complete logging of all AI interactions
- **Privacy Compliance**: GDPR-ready data handling
- **Secure APIs**: REST endpoints with proper authentication

## 🎨 User Interface

### Modern Design

- **Responsive Layout**: Works on desktop, tablet, and mobile
- **Dark Mode Support**: Automatic theme adaptation
- **Intuitive Navigation**: Easy-to-use interface
- **Real-time Updates**: Live dashboards and monitoring
- **Professional Styling**: Clean, modern appearance

### Key Interface Components

- **Provider Management**: Easy configuration of LLM providers
- **API Key Management**: Secure storage and management
- **Request Monitoring**: Real-time view of AI interactions
- **Analytics Dashboard**: Comprehensive usage statistics
- **Settings Panel**: Advanced configuration options

## 🔧 Technical Requirements

### System Requirements

- **Odoo Version**: 18.0 or higher
- **Python Version**: 3.8 or higher
- **Database**: PostgreSQL 12.0 or higher
- **Memory**: Minimum 4GB RAM (8GB recommended)
- **Storage**: 1GB free space

### Dependencies

- **Odoo Modules**: `base`, `web`
- **Python Packages**: `requests`, `json`
- **External Services**: Internet access for LLM APIs

### Supported LLM Providers

| Provider | Models | Features |
|----------|--------|----------|
| **OpenAI** | GPT-4, GPT-3.5, GPT-4o, text-embedding-3-small | Text generation, chat, embeddings, streaming |
| **Google Gemini** | Gemini Pro, Gemini Flash, text-embedding-004 | Text generation, chat, embeddings, streaming |
| **Anthropic Claude** | Claude 3 Opus, Sonnet, Haiku | Text generation, chat, embeddings, streaming |

## 🚀 Use Cases

### Business Applications

- **📧 Email Automation**: Generate personalized emails and responses
- **📊 Report Generation**: Create intelligent business reports
- **🤖 Customer Support**: Build AI-powered chatbots
- **🔍 Data Analysis**: Intelligent insights and summaries
- **📝 Content Creation**: Generate marketing materials and documentation
- **💼 Sales Automation**: AI-powered sales pitches and follow-ups

### Technical Applications

- **🔧 Code Review**: Automated code analysis and suggestions
- **📋 Documentation**: Generate technical documentation
- **🔄 Process Automation**: AI-driven workflow automation
- **📈 Analytics**: Advanced data analysis and reporting
- **🔍 Search Enhancement**: Semantic search capabilities

## 📈 Performance & Optimization

### Best Practices

1. **Model Selection**: Choose appropriate models for your use case
2. **Caching**: Implement caching for frequently requested content
3. **Rate Limiting**: Monitor and respect API rate limits
4. **Error Handling**: Implement robust error handling
5. **Monitoring**: Use built-in analytics to optimize usage

### Performance Tips

- Use streaming for long responses
- Implement request batching where possible
- Monitor token usage to control costs
- Use appropriate temperature settings
- Leverage function calling for complex tasks

## 🔧 Configuration

### Environment Variables

```bash
# Optional: Custom encryption key for keychain
ODOO_KEYCHAIN_KEY=your_custom_key

# Optional: Default provider
AI_AUTOMATION_DEFAULT_PROVIDER=openai

# Optional: Rate limiting settings
AI_AUTOMATION_RATE_LIMIT_RPM=1000
AI_AUTOMATION_RATE_LIMIT_TPM=50000
```

### System Parameters

Configure via Odoo Settings → Technical → Parameters:

- `ai_automation_base.default_provider`: Default LLM provider
- `ai_automation_base.rate_limit_rpm`: Requests per minute limit
- `ai_automation_base.rate_limit_tpm`: Tokens per minute limit
- `ai_automation_base.cache_ttl`: Cache time-to-live in seconds

## 🐛 Troubleshooting

### Common Issues

#### API Key Errors
```
Error: Invalid API key
Solution: Verify API key in AI Automation → API Keys
```

#### Rate Limiting
```
Error: Rate limit exceeded
Solution: Check usage in Analytics dashboard
```

#### Connection Issues
```
Error: Connection timeout
Solution: Verify internet connection and API endpoints
```

### Debug Mode

Enable debug logging:
```python
# In Odoo configuration
log_level = debug
log_handler = [':DEBUG:ai_automation_base:DEBUG']
```

### Support

For technical support:
- **Email**: info@ecosire.com
- **Documentation**: [Module Documentation](https://www.ecosire.com/docs)
- **Issues**: [GitHub Issues](https://github.com/ecosire/ai_automation_base/issues)

## 🔄 Updates & Maintenance

### Version History

- **v1.0.0**: Initial release with OpenAI, Gemini, and Claude support
- **v1.1.0**: Added function calling framework
- **v1.2.0**: Enhanced analytics and monitoring
- **v1.3.0**: Improved security and performance

### Migration Guide

When upgrading between major versions:
1. Backup your database
2. Update the module via Odoo Apps
3. Review configuration changes
4. Test all AI integrations
5. Update any custom code if needed

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/ecosire/ai_automation_base.git

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/

# Create pull request
```

## 📄 License

This module is licensed under the LGPL-3 License. See [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Odoo Community**: For the excellent framework
- **OpenAI**: For GPT models and API
- **Google**: For Gemini models and API
- **Anthropic**: For Claude models and API
- **OCA**: For the keychain module

## 📞 Contact

- **Company**: ECOSIRE (PRIVATE) LIMITED
- **Website**: https://www.ecosire.com
- **Email**: info@ecosire.com
- **Support**: info@ecosire.com

---

**Built with ❤️ by ECOSIRE for the Odoo Community**

*Transform your Odoo with the power of AI!* 