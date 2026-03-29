package lat.ssganador.loteriatv

import android.app.Application

class LoteriaTvApp : Application() {
    override fun onCreate() {
        super.onCreate()
        PersistentLogger.init(this)
        PersistentLogger.i("LIFECYCLE", "Logger inicializado (Application)")
    }
}
