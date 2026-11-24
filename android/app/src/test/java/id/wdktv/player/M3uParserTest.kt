package id.wdktv.player

import org.junit.Assert.assertEquals
import org.junit.Test

class M3uParserTest {
    @Test
    fun parsesAttributesHeadersAndCommaInName() {
        val text = """
            #EXTM3U
            #EXTINF:-1 tvg-id="A" group-title="G, H" tvg-logo="http://l/x.png", Nama, Koma
            #EXTVLCOPT:http-referrer=https://r/
            #EXTVLCOPT:http-user-agent=ua
            https://h/a.m3u8|Origin=https://o
            #EXTINF:-1, Tanpa URL
            #EXTINF:-1 group-title="X", Dua
            https://h/b.mpd
        """.trimIndent()
        val ch = M3uParser.parse(text)
        assertEquals(2, ch.size)
        assertEquals("Nama, Koma", ch[0].name)
        assertEquals("G, H", ch[0].group)
        assertEquals("https://h/a.m3u8", ch[0].url)
        assertEquals("https://r/", ch[0].headers["Referer"])
        assertEquals("ua", ch[0].headers["User-Agent"])
        assertEquals("https://o", ch[0].headers["Origin"])
        assertEquals("Dua", ch[1].name)
    }
}
