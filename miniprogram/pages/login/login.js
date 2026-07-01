// pages/login/login.js
const api = require('../../utils/api');

Page({
  data: {
    phone: '',
    password: '',
    rememberLogin: false,
    loading: false,
    errorMsg: '',
    // 服务器地址配置
    serverUrl: 'https://api.waterguard.online',
    showServerInput: true,   // 默认展开，方便首次配置
    testing: false,
    testResult: '',          // 连接测试结果
    serverDetails: null,     // 服务器健康信息
  },

  onLoad() {
    // 读取已保存的服务器地址
    const savedUrl = wx.getStorageSync('waterGuardBaseUrl');
    if (savedUrl) {
      this.setData({ serverUrl: savedUrl, showServerInput: false });
      api.setBaseUrl(savedUrl);
    }
    // 自动填充记住的手机号
    const savedPhone = wx.getStorageSync('waterGuardPhone');
    if (savedPhone) {
      this.setData({ phone: savedPhone, rememberLogin: true });
    }
    // 首次打开自动测试连接
    this.testServer();
  },

  toggleServerInput() {
    this.setData({ showServerInput: !this.data.showServerInput });
  },

  onServerUrlInput(e) {
    this.setData({ serverUrl: e.detail.value.trim(), testResult: '', serverDetails: null });
  },

  /** 测试服务器连通性（含健康检查详情） */
  async testServer() {
    const url = this.data.serverUrl.replace(/\/$/, '');
    if (!url) {
      this.setData({ testResult: '请输入服务器地址' });
      return;
    }
    this.setData({ testing: true, testResult: '正在测试...', serverDetails: null });
    const result = await api.testConnection(url);
    this.setData({
      testing: false,
      testResult: result.msg,
      serverDetails: result.details || null,
    });
    if (result.ok) {
      // 连通后自动更新 BASE_URL
      api.setBaseUrl(url);
      wx.setStorageSync('waterGuardBaseUrl', url);
      const app = getApp();
      app.globalData.baseUrl = url;
    }
  },

  onPhoneInput(e) {
    this.setData({ phone: e.detail.value, errorMsg: '' });
  },

  onPasswordInput(e) {
    this.setData({ password: e.detail.value, errorMsg: '' });
  },

  onRememberChange(e) {
    this.setData({ rememberLogin: e.detail.value });
  },

  async onLogin() {
    const { phone, password, rememberLogin, serverUrl } = this.data;
    if (!phone) { this.setData({ errorMsg: '请输入手机号' }); return; }
    if (!password) { this.setData({ errorMsg: '请输入密码' }); return; }

    // 确保 BASE_URL 是最新的
    const url = serverUrl.replace(/\/$/, '');
    api.setBaseUrl(url);

    this.setData({ loading: true, errorMsg: '' });
    try {
      const data = await api.post('/api/login', { phone, password });
      if (data && data.success) {
        wx.setStorageSync('waterGuardBaseUrl', url);
        const app = getApp();
        app.globalData.baseUrl = url;
        app.setUser(data.data.user);
        if (rememberLogin) {
          wx.setStorageSync('waterGuardPhone', phone);
        } else {
          wx.removeStorageSync('waterGuardPhone');
        }
        wx.showToast({ title: '登录成功', icon: 'success', duration: 800 });
        setTimeout(() => {
          wx.switchTab({ url: '/pages/dashboard/dashboard' });
        }, 800);
      } else {
        this.setData({ errorMsg: (data && data.msg) || '手机号或密码错误' });
      }
    } catch (err) {
      console.error('[Login] 失败:', err);
      // ── 离线临时登录：服务器无法连接时，允许使用预设临时账号登录 ──
      const OFFLINE_PHONE = '18723616344';
      const OFFLINE_PWD   = '123456';
      if (phone === OFFLINE_PHONE && password === OFFLINE_PWD) {
        wx.showToast({ title: '离线临时登录', icon: 'none', duration: 1200 });
        const offlineUser = { id: -1, phone: OFFLINE_PHONE, role: 'user', nickname: '临时用户（离线）', offline: true };
        const app = getApp();
        app.setUser(offlineUser);
        if (rememberLogin) {
          wx.setStorageSync('waterGuardPhone', phone);
        } else {
          wx.removeStorageSync('waterGuardPhone');
        }
        setTimeout(() => {
          wx.switchTab({ url: '/pages/dashboard/dashboard' });
        }, 1200);
      } else {
        let msg = '无法连接服务器';
        if (err && err.msg) {
          msg = err.msg;
        } else if (err && err.errMsg) {
          if (err.errMsg.indexOf('url not in domain list') > -1) {
            msg = '请在"详情→本地设置"中勾选"不校验合法域名"';
          } else if (err.errMsg.indexOf('timeout') > -1) {
            msg = '连接超时，请检查地址和后端是否运行';
          } else {
            msg = '连接失败: ' + err.errMsg.substring(0, 60);
          }
        }
        this.setData({ errorMsg: msg });
      }
    } finally {
      this.setData({ loading: false });
    }
  },
});
