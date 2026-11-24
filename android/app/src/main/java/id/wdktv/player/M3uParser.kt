package id.wdktv.player

/** Satu channel hasil baca M3U. */
data class Channel(
    val name: String,
    val url: String,
    val group: String = "",
    val logo: String = "",
    val headers: Map<String, String> = emptyMap(),
)

/**
 * Parser M3U murni Kotlin (tanpa Android) sehingga bisa diuji dengan JUnit biasa.
 * Perilakunya disamakan dengan tools/m3ulib.py di sisi Python.
 */
object M3uParser {
    private val attrRe = Regex("""([A-Za-z0-9_\-]+)="([^"]*)"""")

    fun parse(text: String): List<Channel> {
        val out = mutableListOf<Channel>()
        var name = ""
        var attrs: Map<String, String> = emptyMap()
        var opts = mutableMapOf<String, String>()
        var have = false

        for (raw in text.lineSequence()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#EXTM3U")) continue
            when {
                line.startsWith("#EXTINF:") -> {
                    val body = line.removePrefix("#EXTINF:")
                    attrs = attrRe.findAll(body).associate { it.groupValues[1] to it.groupValues[2] }
                    val rest = attrRe.replace(body, "")
                    name = rest.substringAfter(",", "").trim()
                    opts = mutableMapOf()
                    have = true
                }
                line.startsWith("#EXTVLCOPT:") -> {
                    val kv = line.removePrefix("#EXTVLCOPT:")
                    val k = kv.substringBefore("=").trim().lowercase()
                    val v = kv.substringAfter("=", "").trim()
                    when (k) {
                        "http-user-agent" -> opts["User-Agent"] = v
                        "http-referrer" -> opts["Referer"] = v
                        "http-origin" -> opts["Origin"] = v
                    }
                }
                line.startsWith("#") -> Unit // KODIPROP, komentar, dll. -> diabaikan
                else -> if (have) {
                    val pipe = line.substringAfter("|", "")
                    val headers = opts.toMutableMap()
                    if (pipe.isNotEmpty()) {
                        pipe.split("&").forEach { p ->
                            if ("=" in p) headers[p.substringBefore("=").trim()] = p.substringAfter("=").trim()
                        }
                    }
                    out += Channel(
                        name = name.ifEmpty { attrs["tvg-name"] ?: line },
                        url = line.substringBefore("|").trim(),
                        group = attrs["group-title"] ?: "",
                        logo = attrs["tvg-logo"] ?: "",
                        headers = headers,
                    )
                    have = false
                }
            }
        }
        return out
    }
}
