// pages/dashboard/dashboard.js
const api = require('../../utils/api');

Page({
  data: {
    stats: { online_devices: '--', today_urgent: '--', today_records: '--', person_count: '--', run_hours: '--' },
    alarmList: [],
    cameras: [],
    gridMode: true,
    activeCamera: null,
    wsConnected: false,
    loading: true,
    cameraLoading: true,
  },

  _statsTimer: null,
  _snapshotTimer: null,
  _socketTask: null,
  _heartbeatTimer: null,
  _reconnectTimer: null,
  _reconnectAttempts: 0,
  _maxReconnectDelay: 30000,

  onLoad() {
    const app = getApp();
    if (!app.globalData.userInfo) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.loadStats();
    this.loadAlarms();
    this.loadCameras();
    this.connectWs();
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 0 });
    }
    // 定时刷新统计（10s）
    this._statsTimer = setInterval(() => this.loadStats(), 10000);
    // 轮询快照刷新（每5秒）
    this._snapshotTimer = setInterval(() => this.refreshSnapshots(), 5000);
  },

  onHide() {
    if (this._statsTimer) { clearInterval(this._statsTimer); this._statsTimer = null; }
    if (this._snapshotTimer) { clearInterval(this._snapshotTimer); this._snapshotTimer = null; }
  },

  onUnload() {
    this.onHide();
    this.disconnectWs();
  },

  onPullDownRefresh() {
    Promise.all([this.loadStats(), this.loadAlarms(), this.loadCameras()]).finally(() => {
      wx.stopPullDownRefresh();
    });
  },

  // ────────────────────────────────────────
  // 摄像头相关
  // ────────────────────────────────────────

  /**
   * 从后端获取摄像头列表
   */
  async loadCameras() {
    this.setData({ cameraLoading: true });
    try {
      const data = await api.get('/api/cameras');
      if (Array.isArray(data)) {
        const cameras = data.map(cam => ({
          ...cam,
          snapshotUrl: this.buildSnapshotUrl(cam.camera_id),
        }));
        this.setData({ cameras });
      } else {
        this.setData({ cameras: [] });
      }
    } catch (err) {
      console.error('[Dashboard] 获取摄像头列表失败:', err);
      this.setData({ cameras: [] });
    }
    this.setData({ cameraLoading: false });
  },

  /**
   * 构造摄像头快照URL（带时间戳防缓存）
   */
  buildSnapshotUrl(cameraId) {
    return api.fullUrl('/api/cameras/' + cameraId + '/snapshot') + '?t=' + Date.now();
  },

  /**
   * 定时刷新所有摄像头的快照
   */
  refreshSnapshots() {
    const cameras = this.data.cameras;
    if (!cameras || cameras.length === 0) return;

    const updated = cameras.map(cam => ({
      ...cam,
      snapshotUrl: this.buildSnapshotUrl(cam.camera_id),
    }));
    this.setData({ cameras: updated });

    // 如果当前在全屏模式，也刷新 activeCamera 的快照
    if (!this.data.gridMode && this.data.activeCamera) {
      this.setData({
        'activeCamera.snapshotUrl': this.buildSnapshotUrl(this.data.activeCamera.camera_id),
      });
    }
  },

  /**
   * 点击摄像头进入全屏查看
   */
  onCameraTap(e) {
    const cameraId = e.currentTarget.dataset.id;
    const camera = this.data.cameras.find(c => c.camera_id === cameraId);
    if (!camera) return;

    this.setData({
      gridMode: false,
      activeCamera: {
        ...camera,
        snapshotUrl: this.buildSnapshotUrl(camera.camera_id),
      },
    });
  },

  /**
   * 从全屏返回网格视图
   */
  onBackToGrid() {
    this.setData({
      gridMode: true,
      activeCamera: null,
    });
  },

  /**
   * 手动刷新摄像头列表
   */
  onRefreshCameras() {
    wx.showLoading({ title: '刷新中...', mask: true });
    this.loadCameras().finally(() => {
      wx.hideLoading();
    });
  },

  // ────────────────────────────────────────
  // 统计与预警
  // ────────────────────────────────────────

  async loadStats() {
    try {
      const data = await api.get('/api/stats');
      if (data) {
        this.setData({
          stats: {
            online_devices: data.online_devices ?? '--',
            today_urgent: data.today_urgent ?? '--',
            today_records: data.today_records ?? '--',
            person_count: data.person_count ?? '--',
            run_hours: data.run_hours ?? '--',
          },
        });
      }
    } catch (_) {}
  },

  async loadAlarms() {
    this.setData({ loading: true });
    try {
      const list = await api.get('/alarms');
      if (Array.isArray(list)) {
        this.setData({
          alarmList: list.slice(0, 30).map(a => ({
            ...a,
            levelLabel: this.levelLabel(a.level),
          })),
        });
      }
    } catch (_) {}
    this.setData({ loading: false });
  },

  levelLabel(l) {
    return l === 'urgent' ? '紧急' : l === 'warning' ? '警告' : '记录';
  },

  levelClass(l) {
    return l === 'urgent' ? 'badge-urgent' : l === 'warning' ? 'badge-warning' : 'badge-info';
  },

  // ────────────────────────────────────────
  // WebSocket（带指数退避重连）
  // ────────────────────────────────────────

  connectWs() {
    this.disconnectWs();

    const wsUrl = api.fullUrl('/ws').replace(/^http/, 'ws');
    console.log('[WS] 连接:', wsUrl);

    try {
      this._socketTask = wx.connectSocket({ url: wsUrl });

      this._socketTask.onOpen(() => {
        console.log('[WS] 已连接');
        this.setData({ wsConnected: true });
        this._reconnectAttempts = 0;

        // 心跳保活（30s）
        this._heartbeatTimer = setInterval(() => {
          if (this._socketTask) {
            this._socketTask.send({ data: 'ping' }).catch(() => {});
          }
        }, 30000);
      });

      this._socketTask.onMessage((res) => {
        try {
          const msg = JSON.parse(res.data);
          this._handleWsMessage(msg);
        } catch (_) {}
      });

      this._socketTask.onClose((res) => {
        console.log('[WS] 已断开, code:', res.code);
        this.setData({ wsConnected: false });
        this._clearHeartbeat();
        if (!this._manualClose) {
          this._scheduleReconnect();
        }
      });

      this._socketTask.onError((err) => {
        console.error('[WS] 错误:', err);
        this._clearHeartbeat();
      });
    } catch (err) {
      console.error('[WS] 连接异常:', err);
      this._scheduleReconnect();
    }
  },

  /**
   * 处理 WebSocket 消息：alarm / camera_update / stats_update
   */
  _handleWsMessage(msg) {
    const msgType = msg.type;

    if (msgType === 'alarm') {
      const newItem = { ...msg, levelLabel: this.levelLabel(msg.level) };
      const list = [newItem, ...this.data.alarmList].slice(0, 30);
      this.setData({ alarmList: list });
      this.loadStats();
      wx.vibrateShort({ type: 'heavy' });
      return;
    }

    if (msgType === 'detection') {
      // swimming/playing 记录 — 静默追加到列表，不振动
      const newItem = { ...msg, levelLabel: this.levelLabel(msg.level) };
      const list = [newItem, ...this.data.alarmList].slice(0, 30);
      this.setData({ alarmList: list });
      this.loadStats();
      return;
    }

    if (msgType === 'camera_update') {
      // 后端推送摄像头状态变更，刷新摄像头列表
      console.log('[WS] 收到 camera_update，刷新摄像头列表');
      this.loadCameras();
      return;
    }

    if (msgType === 'stats_update') {
      // 后端推送统计更新
      const data = msg.data || msg;
      this.setData({
        stats: {
          online_devices: data.online_devices ?? this.data.stats.online_devices,
          today_urgent: data.today_urgent ?? this.data.stats.today_urgent,
          today_records: data.today_records ?? this.data.stats.today_records,
          person_count: data.person_count ?? this.data.stats.person_count,
          run_hours: data.run_hours ?? this.data.stats.run_hours,
        },
      });
      return;
    }
  },

  /**
   * 指数退避重连
   */
  _scheduleReconnect() {
    if (this._reconnectTimer) return;

    this._reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this._reconnectAttempts - 1), this._maxReconnectDelay);
    console.log(`[WS] ${delay}ms 后重连（第 ${this._reconnectAttempts} 次）`);

    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connectWs();
    }, delay);
  },

  _clearHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
    }
  },

  disconnectWs() {
    this._manualClose = true;
    this._clearHeartbeat();

    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }

    if (this._socketTask) {
      try { this._socketTask.close(); } catch (_) {}
      this._socketTask = null;
    }

    this._manualClose = false;
  },
});
