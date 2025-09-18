//integrations/mcp/cobol/cobol-parser-mcp/vendor/proleap/cli-bridge/src/main/java/com/renova/proleap/CLI.java
package com.renova.proleap;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import io.proleap.cobol.asg.runner.impl.CobolParserRunnerImpl;
import io.proleap.cobol.preprocessor.CobolPreprocessor;

/**
 * Minimal bridge around ProLeap 4.0.0.
 * Usage:
 *   java -cp ... com.renova.proleap.CLI --stdin
 *   java -cp ... com.renova.proleap.CLI <file.cbl>
 */
public class CLI {

  public static void main(String[] args) throws Exception {
    boolean useStdin = false;
    String inFile = null;

    for (String a : args) {
      if ("--stdin".equals(a) || "-stdin".equals(a)) {
        useStdin = true;
      } else if (!a.startsWith("-")) {
        inFile = a;
      }
    }

    File srcFile;
    if (useStdin) {
      byte[] bytes = System.in.readAllBytes();
      if (bytes.length == 0) {
        System.err.println("No data on stdin.");
        System.exit(2);
      }
      srcFile = Files.createTempFile("proleap_cli_", ".cbl").toFile();
      try (OutputStream os = new FileOutputStream(srcFile)) {
        os.write(bytes);
      }
      srcFile.deleteOnExit();
    } else {
      if (inFile == null) {
        System.err.println("Usage: CLI (--stdin | <file.cbl>)");
        System.exit(2);
        return;
      }
      srcFile = new File(inFile);
      if (!srcFile.isFile()) {
        System.err.println("File not found: " + srcFile.getAbsolutePath());
        System.exit(2);
      }
    }

    CobolParserRunnerImpl runner = new CobolParserRunnerImpl();
    // ProLeap will throw if it can’t parse; catch & report
    // Choose a format. Common choices: FIXED or FREE.
    CobolPreprocessor.CobolSourceFormatEnum fmt;

    String fmtEnv = System.getenv("COBOL_SOURCE_FORMAT");
    if ("VARIABLE".equalsIgnoreCase(fmtEnv)) {
        fmt = CobolPreprocessor.CobolSourceFormatEnum.VARIABLE;
    } else {
        // default fallback: FIXED
        fmt = CobolPreprocessor.CobolSourceFormatEnum.FIXED;
    }

    try {
      runner.analyzeFile(srcFile, fmt);
      // Minimal success marker for your Python adapter to detect
      System.out.println("{\"status\":\"ok\",\"file\":\"" + srcFile.getPath().replace("\\","\\\\") + "\"}");
    } catch (Throwable t) {
      // Print a single-line error that your adapter can capture
      String msg = t.getMessage();
      if (msg == null) msg = t.getClass().getName();
      System.out.println("{\"status\":\"error\",\"message\":\"" +
          msg.replace("\"","\\\"").replace("\n"," ").replace("\r"," ") + "\"}");
      System.exit(1);
    }
  }
}
