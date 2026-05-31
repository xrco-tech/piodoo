FROM python:3.12-slim

RUN pip install --no-cache-dir mcp-proxy mcp-server-odoo

EXPOSE 8080

CMD ["mcp-proxy", \
     "--transport", "streamablehttp", \
     "--port", "8080", \
     "--host", "0.0.0.0", \
     "--pass-environment", \
     "--", \
     "mcp-server-odoo"]
