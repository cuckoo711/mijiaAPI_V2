package com.cuckoo.mijia.standalone;

import android.content.*;
import android.os.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Private, same-UID IPC: the console never owns the Python interpreter. */
public final class ServerConnection implements ServiceConnection {
    private final Context context;
    private volatile Messenger remote;
    private boolean bound;
    private final AtomicInteger ids = new AtomicInteger();
    private final ConcurrentHashMap<Integer, CompletableFuture<Bundle>> pending = new ConcurrentHashMap<>();
    public volatile boolean connected, active, ready;
    public volatile String status = "服务未启动", ownerToken = "";
    public volatile int pid;
    private final Messenger client = new Messenger(new Handler(Looper.getMainLooper()) {
        @Override public void handleMessage(Message message) {
            Bundle data = message.getData();
            if (message.what == ServerService.STATUS) {
                active = data.getBoolean("active"); ready = data.getBoolean("ready");
                status = data.getString("status", "服务未启动");
                ownerToken = data.getString("owner", ""); pid = data.getInt("pid");
            } else if (message.what == ServerService.DEBUG_ACCEPTANCE) {
                CompletableFuture<Bundle> future = pending.remove(message.arg1);
                if (future != null) future.complete(data);
            }
        }
    });

    public ServerConnection(Context context) { this.context = context; }
    public void bind() {
        if (!bound) bound = context.bindService(new Intent(context, ServerService.class), this, Context.BIND_AUTO_CREATE);
    }
    public void unbind() {
        if (bound) context.unbindService(this);
        bound = false; connected = false; ready = false; remote = null;
    }
    @Override public void onServiceConnected(ComponentName name, IBinder binder) {
        remote = new Messenger(binder); connected = true; refresh();
    }
    @Override public void onServiceDisconnected(ComponentName name) {
        remote = null; connected = false; ready = false; active = false;
        status = "正在重新连接服务…";
    }
    private void send(Message message) throws RemoteException {
        Messenger service = remote;
        if (service == null) throw new RemoteException("Service is not connected");
        message.replyTo = client; service.send(message);
    }
    public void refresh() {
        if (remote != null) try { send(Message.obtain(null, ServerService.STATUS)); }
        catch (RemoteException ignored) { connected = false; ready = false; }
    }
    /** Only the debug instrumentation calls this; the Service verifies UID and debug flag. */
    public String acceptance(String mode, String password) throws Exception {
        int id = ids.incrementAndGet();
        CompletableFuture<Bundle> future = new CompletableFuture<>(); pending.put(id, future);
        Message message = Message.obtain(null, ServerService.DEBUG_ACCEPTANCE); message.arg1 = id;
        Bundle data = new Bundle(); data.putString("mode", mode); data.putString("password", password); message.setData(data);
        try {
            send(message);
            Bundle result = future.get(120, TimeUnit.SECONDS);
            if (result.containsKey("error")) throw new IllegalStateException(result.getString("error"));
            return result.getString("result");
        } finally { pending.remove(id); }
    }
}
