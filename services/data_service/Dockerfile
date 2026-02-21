FROM python:3.11-alpine
WORKDIR /app
RUN pip install --no-cache-dir flask==3.0.0
COPY app.py .
ENV SERVICE_NAME=data-service
EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1
CMD ["python", "app.py"]
