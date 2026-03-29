package lat.ssganador.loteriatv

import android.content.ContentValues
import android.content.Context
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.io.File
import java.io.FileWriter
import java.io.OutputStreamWriter
import java.io.PrintWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Logger persistente que NUNCA debe tumbar la app:
 * - Siempre escribe en almacenamiento interno (filesDir): 100% seguro.
 * - En Android 10+ espejo opcional a Downloads/LoteriaTV/ vía MediaStore (sin permisos).
 * - En Android 9 o menor espejo opcional a /Download/LoteriaTV/ (permiso ya está en manifest con maxSdk=28).
 */
object PersistentLogger {
    private const val ANDROID_TAG = "LoteriaTV"
    private const val FILE_NAME = "loteriatv.log"
    private const val BAK_NAME = "loteriatv.log.bak"
    private const val MAX_BYTES = 2 * 1024 * 1024L
    private const val MIRROR_INTERVAL_MS = 60_000L

    private val initialized = AtomicBoolean(false)
    private val io = Executors.newSingleThreadExecutor()
    private val dateFmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)

    @Volatile private var appCtx: Context? = null
    @Volatile private var internalLogFile: File? = null
    @Volatile private var lastMirrorAtMs: Long = 0L

    fun init(context: Context) {
        if (!initialized.compareAndSet(false, true)) return
        appCtx = context.applicationContext
        internalLogFile = File(appCtx!!.filesDir, FILE_NAME)
        writeLine("INFO ", "LOGGER", "init: filesDir=${appCtx!!.filesDir.absolutePath}")
        mirrorToDownloadsAsync(force = true)
    }

    fun i(tag: String, msg: String) = writeLine("INFO ", tag, msg)
    fun w(tag: String, msg: String) = writeLine("WARN ", tag, msg)
    fun e(tag: String, msg: String) = writeLine("ERROR", tag, msg)

    private fun writeLine(level: String, tag: String, msg: String) {
        val line = "${dateFmt.format(Date())} [$level] [$tag] $msg"
        Log.d(ANDROID_TAG, line)

        val file = internalLogFile
        if (!initialized.get() || file == null) return

        io.execute {
            try {
                rotateIfNeeded(file)
                FileWriter(file, true).use { fw ->
                    PrintWriter(fw).use { pw -> pw.println(line) }
                }
            } catch (t: Throwable) {
                Log.e(ANDROID_TAG, "Logger write failed (internal): ${t.message}")
            }

            // Hacer espejo con throttle para no copiar el archivo completo en cada linea.
            mirrorToDownloadsAsync()
        }
    }

    private fun rotateIfNeeded(file: File) {
        try {
            if (file.exists() && file.length() > MAX_BYTES) {
                val parent = file.parentFile ?: return
                file.copyTo(File(parent, BAK_NAME), overwrite = true)
                file.writeText("")
            }
        } catch (_: Throwable) {
            // No-op (jamás crashear por rotación)
        }
    }

    @Synchronized
    private fun shouldMirrorNow(force: Boolean): Boolean {
        if (force) {
            lastMirrorAtMs = System.currentTimeMillis()
            return true
        }
        val now = System.currentTimeMillis()
        if ((now - lastMirrorAtMs) < MIRROR_INTERVAL_MS) return false
        lastMirrorAtMs = now
        return true
    }

    private fun mirrorToDownloadsAsync(force: Boolean = false) {
        val ctx = appCtx ?: return
        val src = internalLogFile ?: return
        if (!shouldMirrorNow(force)) return

        io.execute {
            try {
                if (!src.exists()) return@execute
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    mirrorToDownloadsMediaStore(ctx, src)
                } else {
                    mirrorToDownloadsLegacy(src)
                }
            } catch (t: Throwable) {
                Log.e(ANDROID_TAG, "Mirror to Downloads failed: ${t.message}")
            }
        }
    }

    private fun mirrorToDownloadsMediaStore(context: Context, src: File) {
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val relativePath = Environment.DIRECTORY_DOWNLOADS + File.separator + "LoteriaTV" + File.separator

        // Crear una nueva entrada (simple). Si quieres "update", lo hacemos luego.
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, FILE_NAME)
            put(MediaStore.Downloads.MIME_TYPE, "text/plain")
            put(MediaStore.Downloads.RELATIVE_PATH, relativePath)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }

        val uri = resolver.insert(collection, values) ?: return

        resolver.openOutputStream(uri, "wt")?.use { os ->
            OutputStreamWriter(os).use { out ->
                out.write(src.readText())
            }
        }

        values.clear()
        values.put(MediaStore.Downloads.IS_PENDING, 0)
        resolver.update(uri, values, null, null)
    }

    @Suppress("DEPRECATION")
    private fun mirrorToDownloadsLegacy(src: File) {
        val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val dir = File(downloads, "LoteriaTV")
        if (!dir.exists()) dir.mkdirs()
        src.copyTo(File(dir, FILE_NAME), overwrite = true)
    }


fun readAll(): String {
    val file = internalLogFile ?: return ""
    return try {
        if (!file.exists()) "" else file.readText()
    } catch (_: Throwable) {
        ""
    }
}

fun readTail(maxChars: Int = 40_000): String {
    val txt = readAll()
    if (txt.length <= maxChars) return txt
    return txt.takeLast(maxChars)
}

fun clear() {
    val file = internalLogFile ?: return
    io.execute {
        try {
            file.writeText("")
        } catch (_: Throwable) {
        }
    }
}

fun internalLogPath(): String {
    val file = internalLogFile ?: return ""
    return file.absolutePath
}
}
