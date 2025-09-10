# services/tools/parsers/languages/cobol/proleap-cb2xml/Dockerfile

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install Java runtime (21) + curl for healthcheck/debug
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      openjdk-21-jre-headless ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# App deps
WORKDIR /svc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app/ app/

# JARs (you provide these two files under ./jars/)
# - proleap-cli.jar : your tiny CLI wrapper around ProLeap
# - cb2xml.jar      : cb2xml release jar
COPY jars/ /opt/jars/

ENV PROLEAP_JAR=/opt/jars/proleap-cli.jar \
    CB2XML_JAR=/opt/jars/cb2xml.jar \
    PORT=8080

EXPOSE 8080
CMD ["python", "-m", "app"]
