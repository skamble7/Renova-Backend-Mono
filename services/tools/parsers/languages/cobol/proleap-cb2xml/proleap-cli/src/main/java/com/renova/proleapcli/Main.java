//services/tools/parsers/languages/cobol/proleap-cb2xml/proleap-cli/src/main/java/com/renova/proleapcli/Main.java
package com.renova.proleapcli;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import java.security.MessageDigest;

public class Main {

    private static final Set<String> DIALECTS = new HashSet<>(Arrays.asList("ANSI85","MF","OSVS"));

    public static void main(String[] args) throws Exception {
        CliArgs cli = parseArgs(args);

        List<String> outputs = new ArrayList<>();
        for (String path : cli.files) {
            try {
                outputs.add(processOne(path, cli.dialect));
            } catch (Exception e) {
                // Represent failures inline (don’t fail the whole batch)
                outputs.add("{\"name\":\"" + json(guessName(path)) + "\",\"path\":\"" + json(path) +
                            "\",\"dialect\":\"" + json(cli.dialect) + "\",\"error\":\"" + json(e.getMessage()) + "\"}");
            }
        }

        StringBuilder sb = new StringBuilder();
        sb.append("{\"programs\":[");
        for (int i = 0; i < outputs.size(); i++) {
            if (i > 0) sb.append(",");
            sb.append(outputs.get(i));
        }
        sb.append("]}");
        System.out.println(sb.toString());
    }

    private static String processOne(String pathStr, String dialect) throws Exception {
        Path p = Paths.get(pathStr);
        String text = Files.readString(p);
        String name = extractProgramId(text);
        if (name == null || name.isEmpty()) {
            name = guessName(pathStr);
        }

        int lines = text.isEmpty() ? 0 : text.split("\\R", -1).length;
        long size = Files.size(p);
        String sha1 = sha1Hex(text);
        String head = text.length() > 512 ? text.substring(0, 512) : text;

        // minimal, ProLeap-shaped payload (you can expand later)
        StringBuilder sb = new StringBuilder();
        sb.append("{");
        kv(sb, "name", name); sb.append(",");
        kv(sb, "path", pathStr); sb.append(",");
        kv(sb, "dialect", dialect); sb.append(",");
        sb.append("\"data\":{");
        kv(sb, "lines", lines); sb.append(",");
        kv(sb, "sizeBytes", size); sb.append(",");
        kv(sb, "sha1", sha1); sb.append(",");
        kv(sb, "sourceHead", head);
        sb.append("}");
        sb.append("}");
        return sb.toString();
    }

    private static String extractProgramId(String text) {
        // Very simple PROGRAM-ID extractor; tolerant to spacing, case, trailing dot.
        // Example matches: "PROGRAM-ID. MYPROG." or "PROGRAM-ID.    MY-PROG"
        var lines = text.split("\\R");
        for (String ln : lines) {
            String s = ln.trim();
            String u = s.toUpperCase(Locale.ROOT);
            if (u.contains("PROGRAM-ID")) {
                // take token after "PROGRAM-ID."
                int idx = u.indexOf("PROGRAM-ID");
                String after = s.substring(idx + "PROGRAM-ID".length());
                after = after.replaceFirst("^\\s*\\.", "");      // remove immediate dot
                after = after.trim();
                if (!after.isEmpty()) {
                    // first token up to space or dot
                    String tok = after.split("[\\s.]", 2)[0];
                    // sanitize :)
                    tok = tok.replaceAll("[^A-Za-z0-9_\\-]+", "");
                    if (!tok.isEmpty()) return tok.toUpperCase(Locale.ROOT);
                }
            }
        }
        return null;
    }

    private static String guessName(String path) {
        String base = Paths.get(path).getFileName().toString();
        int dot = base.lastIndexOf('.');
        if (dot > 0) base = base.substring(0, dot);
        return base.toUpperCase(Locale.ROOT);
    }

    private static String sha1Hex(String s) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-1");
        byte[] dig = md.digest(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte b : dig) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    // --- tiny CLI/JSON helpers ---

    static class CliArgs {
        String dialect = "ANSI85";
        String format = "json";
        List<String> files = new ArrayList<>();
    }

    private static CliArgs parseArgs(String[] args) {
        CliArgs cli = new CliArgs();
        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            if ("--dialect".equals(a) && i + 1 < args.length) {
                String d = args[++i].toUpperCase(Locale.ROOT);
                cli.dialect = DIALECTS.contains(d) ? d : "ANSI85";
            } else if ("--format".equals(a) && i + 1 < args.length) {
                cli.format = args[++i].toLowerCase(Locale.ROOT);
            } else if (a.startsWith("--")) {
                // ignore unknown flags
            } else {
                cli.files.add(a);
            }
        }
        if (!"json".equals(cli.format)) {
            System.err.println("Only --format json is supported.");
            System.exit(2);
        }
        if (cli.files.isEmpty()) {
            System.err.println("Usage: java -jar proleap-cli.jar --dialect ANSI85 --format json <file1> [file2 ...]");
            System.exit(2);
        }
        return cli;
    }

    private static void kv(StringBuilder sb, String key, String val) {
        sb.append("\"").append(json(key)).append("\":\"").append(json(val)).append("\"");
    }
    private static void kv(StringBuilder sb, String key, int val) {
        sb.append("\"").append(json(key)).append("\":").append(val);
    }
    private static void kv(StringBuilder sb, String key, long val) {
        sb.append("\"").append(json(key)).append("\":").append(val);
    }
    private static String json(String s) {
        if (s == null) return "";
        StringBuilder out = new StringBuilder(s.length() + 16);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '\\': out.append("\\\\"); break;
                case '"':  out.append("\\\""); break;
                case '\n': out.append("\\n");  break;
                case '\r': out.append("\\r");  break;
                case '\t': out.append("\\t");  break;
                default:
                    if (c < 32) out.append(String.format("\\u%04x", (int)c));
                    else out.append(c);
            }
        }
        return out.toString();
    }
}
