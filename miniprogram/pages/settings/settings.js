// pages/settings/settings.js
const api = require('../../utils/api');

Page({
  data: {
    serverUrl: 'https://gills-register-prescribe.ngrok-free.dev',
    sensitivity: 80,
    sensitivityOptions: ['低（60）', '中（75）', '高（85）', '极高（95）'],
    sensitivityValues: [60, 75, 85, 95],
    sensitivityIndex: 2,  // 默认高
    soundAlarm: true,
    pushNotify: true,
    autoRecord: false,
    // 密码修改
    showPwdForm: false,
    oldPwd: '',
    newPwd: '',
    confirmPwd: '',
    // 用户信息
    userPhone: '',
    saving: false,
    pwdSaving: false,
  },

  onLoad() {
    const app = getApp();
    if (!app.globalData.userInfo) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.setData({ userPhone: app.globalData.userInfo.phone || '13800138000' });
    this.loadSettings();
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 3 });
    }
  },

  async loadSettings() {
    try {
      const data = await api.get('/api/settings');
      if (!data) return;
      const updates = {};
      if (data.server_url) updates.serverUrl = data.server_url;
      if (data.sensitivity) {
        const val = parseInt(data.sensitivity, 10);
        updates['sensitivity'] = val;
        // 找最近的 index
        const vals = this.data.sensitivityValues;
        let nearest = 0;
        vals.forEach((v, i) => { if (Math.abs(v - val) <= Math.abs(vals[nearest] - val)) nearest = i; });
        updates.sensitivityIndex = nearest;
      }
      if (data.sound_alarm !== undefined) updates.soundAlarm = data.sound_alarm === 'true';
      if (data.push_notify !== undefined) updates.pushNotify = data.push_notify === 'true';
      if (data.auto_record !== undefined) updates.autoRecord = data.auto_record === 'true';
      this.setData(updates);
    } catch (_) {}
  },

  onServerUrlInput(e) { this.setData({ serverUrl: e.detail.value }); },

  onSensitivityChange(e) {
    const idx = e.detail.value;
    this.setData({
      sensitivityIndex: idx,
      sensitivity: this.data.sensitivityValues[idx],
    });
  },

  onSoundAlarmChange(e) { this.setData({ soundAlarm: e.detail.value }); },
  onPushNotifyChange(e) { this.setData({ pushNotify: e.detail.value }); },
  onAutoRecordChange(e) { this.setData({ autoRecord: e.detail.value }); },

  async saveSettings() {
    this.setData({ saving: true });
    const { serverUrl, sensitivity, soundAlarm, pushNotify, autoRecord } = this.data;
    try {
      const data = await api.post('/api/settings', {
        settings: {
          server_url: serverUrl || 'https://gills-register-prescribe.ngrok-free.dev',
          sensitivity: String(sensitivity),
          sound_alarm: String(soundAlarm),
          push_notify: String(pushNotify),
          auto_record: String(autoRecord),
        },
      });
      if (data && data.success) {
        // 更新本地 BASE_URL
        if (serverUrl) {
          wx.setStorageSync('waterGuardBaseUrl', serverUrl);
          api.setBaseUrl(serverUrl);
          const app = getApp();
          app.globalData.baseUrl = serverUrl;
        }
        wx.showToast({ title: '保存成功', icon: 'success' });
      } else {
        wx.showToast({ title: '保存失败', icon: 'none' });
      }
    } catch (_) {
      wx.showToast({ title: '请求失败', icon: 'none' });
    }
    this.setData({ saving: false });
  },

  togglePwdForm() {
    this.setData({
      showPwdForm: !this.data.showPwdForm,
      oldPwd: '', newPwd: '', confirmPwd: '',
    });
  },

  onOldPwdInput(e) { this.setData({ oldPwd: e.detail.value }); },
  onNewPwdInput(e) { this.setData({ newPwd: e.detail.value }); },
  onConfirmPwdInput(e) { this.setData({ confirmPwd: e.detail.value }); },

  async changePassword() {
    const { oldPwd, newPwd, confirmPwd, userPhone } = this.data;
    if (!oldPwd) { wx.showToast({ title: '请输入原密码', icon: 'none' }); return; }
    if (!newPwd) { wx.showToast({ title: '请输入新密码', icon: 'none' }); return; }
    if (newPwd !== confirmPwd) { wx.showToast({ title: '两次密码不一致', icon: 'none' }); return; }
    if (newPwd.length < 6) { wx.showToast({ title: '新密码不能少于6位', icon: 'none' }); return; }

    this.setData({ pwdSaving: true });
    try {
      const data = await api.post('/api/change-password', {
        phone: userPhone,
        old_password: oldPwd,
        new_password: newPwd,
      });
      if (data && data.success) {
        wx.showToast({ title: '修改成功，请重新登录', icon: 'success' });
        setTimeout(() => this.logout(), 1500);
      } else {
        wx.showToast({ title: (data && data.msg) || '修改失败', icon: 'none' });
      }
    } catch (_) {
      wx.showToast({ title: '请求失败', icon: 'none' });
    }
    this.setData({ pwdSaving: false });
  },

  logout() {
    wx.showModal({
      title: '退出登录',
      content: '确定要退出当前账号吗？',
      confirmColor: '#ef5350',
      success: (res) => {
        if (res.confirm) {
          const app = getApp();
          // 清除全局状态
          app.globalData.userInfo = null;
          // 清除本地存储
          wx.removeStorageSync('waterGuardUser');
          // 延迟跳转，避免 tabBar 页面 reLaunch 失效
          setTimeout(() => {
            wx.reLaunch({
              url: '/pages/login/login',
              fail: () => {
                // reLaunch 失败时尝试 redirectTo
                wx.redirectTo({
                  url: '/pages/login/login',
                  fail: () => {
                    // 最后兜底：switchTab 到首页再 reLaunch
                    wx.switchTab({
                      url: '/pages/dashboard/dashboard',
                      success: () => {
                        setTimeout(() => {
                          wx.reLaunch({ url: '/pages/login/login' });
                        }, 300);
                      }
                    });
                  }
                });
              }
            });
          }, 150);
        }
      }
    });
  },
});
