Component({
  data: {
    selected: 0,
    list: [
      { pagePath: '/pages/dashboard/dashboard', text: '监控', icon: 'monitor' },
      { pagePath: '/pages/alarms/alarms',       text: '预警', icon: 'alarm' },
      { pagePath: '/pages/devices/devices',      text: '设备', icon: 'device' },
      { pagePath: '/pages/settings/settings',     text: '设置', icon: 'settings' },
    ],
  },

  methods: {
    switchTab(e) {
      const idx = e.currentTarget.dataset.index;
      const item = this.data.list[idx];
      wx.switchTab({ url: item.pagePath });
    },
  },
});
