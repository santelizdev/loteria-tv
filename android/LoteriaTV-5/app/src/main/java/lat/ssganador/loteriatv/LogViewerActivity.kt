package lat.ssganador.loteriatv

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class LogViewerActivity : AppCompatActivity() {

    private val handler = Handler(Looper.getMainLooper())
    private lateinit var tvLogs: TextView

    private val refreshRunnable = object : Runnable {
        override fun run() {
            refresh()
            handler.postDelayed(this, 1000L)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_log_viewer)

        tvLogs = findViewById(R.id.tvLogs)

        findViewById<Button>(R.id.btnRefresh).setOnClickListener { refresh() }
        findViewById<Button>(R.id.btnClear).setOnClickListener {
            PersistentLogger.clear()
            refresh()
        }
        findViewById<Button>(R.id.btnClose).setOnClickListener { finish() }

        refresh()
    }

    override fun onResume() {
        super.onResume()
        handler.post(refreshRunnable)
    }

    override fun onPause() {
        handler.removeCallbacks(refreshRunnable)
        super.onPause()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK || keyCode == KeyEvent.KEYCODE_ESCAPE) {
            finish()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun refresh() {
        val text = PersistentLogger.readTail()
        val header = buildString {
            append("Log interno: ")
            append(PersistentLogger.internalLogPath())
            append("\n\n")
        }
        tvLogs.text = header + if (text.isBlank()) "(sin logs aún)" else text
    }
}
