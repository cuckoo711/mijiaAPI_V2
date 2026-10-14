package com.cuckoo.mijia.standalone;

import android.app.*;
import android.content.Intent;
import android.os.*;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.atomic.AtomicBoolean;

/** A user-started foreground service owns the embedded interpreter and HTTP listener. */
public class ServerService extends Service {
    public static final String STOP = "com.cuckoo.mijia.standalone.STOP";
    public static volatile boolean active = false;
    public static volatile boolean ready = false;
    public static volatile String status = "服务未启动";
    private final AtomicBoolean started = new AtomicBoolean();
    private volatile boolean stopping;
    private PowerManager.WakeLock wakeLock;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override public IBinder onBind(Intent intent) { return null; }

    private Notification notification() {
        String channel = "mijia_server";
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(
                new NotificationChannel(channel, "独立服务", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, ServerService.class).setAction(STOP), PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, channel) : new Notification.Builder(this);
        return builder.setSmallIcon(com.cuckoo.mijia.standalone.R.drawable.ic_service)
                .setContentTitle("米家独立服务").setContentText("手机正在提供服务，点击打开管理台")
                .setOngoing(true).setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "停止服务", stop).build()).build();
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && STOP.equals(intent.getAction())) {
            requestStop(); return START_NOT_STICKY;
        }
        if (!started.compareAndSet(false, true)) return START_STICKY;
        active = true; ready = false; stopping = false; status = "正在启动 Python 服务…";
        startForeground(1, notification());
        wakeLock = ((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "mijia:server");
        wakeLock.acquire();
        boolean lan = getSharedPreferences("server", MODE_PRIVATE).getBoolean("lan", false);
        new Thread(() -> {
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
                if (!stopping) Python.getInstance().getModule("mijia_android.runtime").callAttr("prepare");
                if (!stopping) Python.getInstance().getModule("mijia_android.runtime")
                        .callAttr("run", getFilesDir().getAbsolutePath() + "/service", lan);
            } catch (Throwable error) {
                // Do not put potentially credential-bearing exception messages into notifications.
                status = "启动失败：" + error.getClass().getSimpleName() + "（请导出诊断日志）";
                android.util.Log.e("MijiaServer", "Embedded runtime failed", error);
            } finally {
                active = false; ready = false;
                if (stopping) status = "服务已停止";
                else if (!status.startsWith("启动失败")) status = "服务已退出，请检查日志后重新启动";
                handler.post(this::stopSelf);
            }
        }, "mijia-python").start();
        new Thread(() -> {
            while (active && !stopping) {
                HttpURLConnection connection = null;
                try {
                    connection = (HttpURLConnection)new URL("http://127.0.0.1:8123/readyz").openConnection();
                    connection.setConnectTimeout(1500); connection.setReadTimeout(1500);
                    ready = connection.getResponseCode() == 200;
                    if (ready) status = "服务运行正常 · 127.0.0.1:8123";
                } catch (Exception ignored) { ready = false; }
                finally { if (connection != null) connection.disconnect(); }
                try { Thread.sleep(2000); } catch (InterruptedException ignored) { break; }
            }
        }, "mijia-health").start();
        return START_STICKY;
    }

    private void requestStop() {
        stopping = true; ready = false; status = "正在停止服务…";
        new Thread(() -> {
            if (Python.isStarted()) Python.getInstance().getModule("mijia_android.runtime").callAttr("stop");
            if (!active) handler.post(this::stopSelf);
        }, "mijia-stop").start();
    }

    @Override public void onDestroy() {
        if (active) requestStop();
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        stopForeground(true);
        super.onDestroy();
    }
}
