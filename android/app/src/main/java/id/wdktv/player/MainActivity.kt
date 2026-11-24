package id.wdktv.player

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Layar utama: tempel URL playlist M3U (mis. link "raw" GitHub), tekan Muat,
 * cari channel, lalu ketuk untuk memutar. UI dibuat lewat kode agar proyek tetap kecil.
 */
class MainActivity : AppCompatActivity() {

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private var all: List<Channel> = emptyList()
    private var shown: List<Channel> = emptyList()
    private lateinit var adapter: ArrayAdapter<String>
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val prefs = getSharedPreferences("wdktv", Context.MODE_PRIVATE)

        val urlBox = EditText(this).apply {
            hint = "URL playlist .m3u (mis. https://raw.githubusercontent.com/.../id.m3u)"
            setText(prefs.getString("url", ""))
            setSingleLine()
        }
        val load = Button(this).apply { text = "Muat playlist" }
        val search = EditText(this).apply { hint = "Cari channel / grup"; setSingleLine() }
        status = TextView(this).apply { text = "Belum ada playlist dimuat." }
        val list = ListView(this)
        adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, mutableListOf())
        list.adapter = adapter

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
            addView(urlBox, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            addView(load, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            addView(search, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            addView(status, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT))
            addView(list, LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
        }
        setContentView(root)

        load.setOnClickListener {
            val url = urlBox.text.toString().trim()
            if (!url.startsWith("http")) {
                Toast.makeText(this, "Isi URL yang diawali http/https", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            prefs.edit().putString("url", url).apply()
            loadPlaylist(url, search.text.toString())
        }
        search.addTextChangedListener(object : TextWatcher {
            override fun afterTextChanged(s: Editable?) = applyFilter(s?.toString().orEmpty())
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) = Unit
        })
        list.setOnItemClickListener { _, _, pos, _ ->
            val ch = shown.getOrNull(pos) ?: return@setOnItemClickListener
            startActivity(Intent(this, PlayerActivity::class.java).apply {
                putExtra(PlayerActivity.EXTRA_NAME, ch.name)
                putExtra(PlayerActivity.EXTRA_URL, ch.url)
                putExtra(PlayerActivity.EXTRA_HEADERS, HashMap(ch.headers))
            })
        }
        if (urlBox.text.isNotBlank()) load.performClick()
    }

    private fun loadPlaylist(url: String, filter: String) {
        status.text = "Memuat ..."
        Thread {
            try {
                val body = http.newCall(Request.Builder().url(url).build()).execute().use { r ->
                    if (!r.isSuccessful) error("HTTP ${r.code}")
                    r.body?.string().orEmpty()
                }
                val parsed = M3uParser.parse(body)
                runOnUiThread {
                    all = parsed
                    applyFilter(filter)
                    status.text = "${parsed.size} channel dimuat."
                }
            } catch (e: Exception) {
                runOnUiThread { status.text = "Gagal memuat: ${e.message}" }
            }
        }.start()
    }

    private fun applyFilter(q: String) {
        val k = q.trim().lowercase()
        shown = if (k.isEmpty()) all else all.filter { k in it.name.lowercase() || k in it.group.lowercase() }
        adapter.clear()
        adapter.addAll(shown.map { if (it.group.isEmpty()) it.name else "${it.name}  ·  ${it.group}" })
        adapter.notifyDataSetChanged()
    }
}
