# ReStock Tools

Simple OpenClaw tool plugin.

This package also pins OpenClaw's official Amazon Bedrock provider for the
headless Coordinator runtime. Provider configuration and invocation validation
remain in the Python backend; this plugin does not contain Coordinator logic or
business calculations.

## Build

```bash
npm install
npm run plugin:build
npm run plugin:validate
npm test
```
