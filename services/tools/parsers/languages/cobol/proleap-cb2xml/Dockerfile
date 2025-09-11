# services/tools/parsers/languages/cobol/proleap-cb2xml/Dockerfile
# --- Stage 1: build the tiny Java CLI -------------------------------
FROM openjdk:21-jdk-slim AS cli-build
WORKDIR /build

# copy only sources for deterministic caching
COPY proleap-cli/src/main/java ./src/main/java

# compile and jar with proper Main-Class
RUN javac -source 21 -target 21 -d /build/out $(find src -name '*.java') \
 && jar cfe /build/proleap-cli.jar com.renova.proleapcli.Main -C /build/out . \
 && jar tf /build/proleap-cli.jar | grep -q 'com/renova/proleapcli/Main.class'

# --- Stage 2: runtime (Python + JRE) ---------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Java runtime + curl for health/debug
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jre-headless ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /svc

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app/ app/

# JARs: bring in the just-built CLI and your cb2xml.jar (if present)
RUN mkdir -p /opt/jars
COPY --from=cli-build /build/proleap-cli.jar /opt/jars/proleap-cli.jar
COPY jars/ /opt/jars/

ENV PROLEAP_JAR=/opt/jars/proleap-cli.jar \
    CB2XML_JAR=/opt/jars/cb2xml.jar \
    PORT=8080

EXPOSE 8080
CMD ["python", "-m", "app"]
