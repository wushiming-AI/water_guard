/**
 * 水域溺水防控AI预警系统 - 小程序入口
 */
const api = require('./utils/api');

App({
  globalData: {
    userInfo: null,   // 当前登录用户 {id, phone, role}
    baseUrl: 'https://gills-register-prescribe.ngrok-free.dev',
  },

  onLaunch() {
    // 读取本地存储中保存的 baseUrl
    const savedUrl = wx.getStorageSync('waterGuardBaseUrl');
    if (savedUrl) {
      this.globalData.baseUrl = savedUrl;
      api.setBaseUrl(savedUrl);
    }

    // 检查登录状态
    const storedUser = wx.getStorageSync('waterGuardUser');
    if (storedUser) {
      try {
        const user = JSON.parse(storedUser);
        if (user && user.id) {
          this.globalData.userInfo = user;
          // 已登录，不跳转，让 pages 列表第一个页面（dashboard）正常展示
          return;
        }
      } catch (_) { /* 忽略解析错误 */ }
    }

    // 未登录，跳转到登录页（延迟确保页面栈就绪）
    setTimeout(() => {
      wx.reLaunch({ url: '/pages/login/login' });
    }, 100);
  },

  /**
   * 保存用户信息到全局与本地存储
   * @param {Object} user
   */
  setUser(user) {
    this.globalData.userInfo = user;
    wx.setStorageSync('waterGuardUser', JSON.stringify(user));
  },

  /**
   * 退出登录：清除所有本地存储，跳转登录页
   */
  logout() {
    this.globalData.userInfo = null;
    wx.removeStorageSync('waterGuardUser');
    // 延迟跳转，避免从 tabBar 页面 reLaunch 失效
    setTimeout(() => {
      wx.reLaunch({
        url: '/pages/login/login',
        fail: () => {
          wx.redirectTo({
            url: '/pages/login/login',
            fail: () => {
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
  },
});
