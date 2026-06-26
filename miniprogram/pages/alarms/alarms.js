// pages/alarms/alarms.js
const api = require('../../utils/api');

const PAGE_SIZE = 20;

Page({
  data: {
    alarmList: [],
    loading: false,
    refreshing: false,
    filterDate: '',
    filterLevel: '',
    levelOptions: ['全部', '紧急', '记录'],
    levelIndex: 0,
    page: 1,
    hasMore: true,
    allLoaded: false,
    total: 0,
  },

  onLoad() {
    const app = getApp();
    if (!app.globalData.userInfo) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.loadAlarms(true);
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 });
    }
  },

  onPullDownRefresh() {
    this.setData({ page: 1, alarmList: [], hasMore: true, allLoaded: false });
    this.loadAlarms(true).finally(() => wx.stopPullDownRefresh());
  },

  onReachBottom() {
    if (!this.data.loading && this.data.hasMore) {
      this.loadMore();
    }
  },

  onDateChange(e) {
    this.setData({ filterDate: e.detail.value, page: 1, alarmList: [], hasMore: true, allLoaded: false });
    this.loadAlarms(true);
  },

  onResetFilter() {
    this.setData({ filterDate: '', filterLevel: '', levelIndex: 0, page: 1, alarmList: [], hasMore: true, allLoaded: false });
    this.loadAlarms(true);
  },

  onLevelChange(e) {
    const idx = e.detail.value;
    const levels = ['', 'urgent', 'info'];
    this.setData({ levelIndex: idx, filterLevel: levels[idx], page: 1, alarmList: [], hasMore: true, allLoaded: false });
    this.loadAlarms(true);
  },

  async loadAlarms(reset) {
    if (this.data.loading) return;
    this.setData({ loading: true });
    try {
      const params = {};
      if (this.data.filterDate) params.date_str = this.data.filterDate;
      if (this.data.filterLevel) params.level = this.data.filterLevel;
      const list = await api.get('/alarms', params);
      if (!Array.isArray(list)) { this.setData({ loading: false }); return; }
      const mapped = list.map(a => ({
        ...a,
        levelLabel: this.levelLabel(a.level),
        timeShort: a.time ? a.time.substring(0, 16) : '--',
      }));
      // 前端分页
      const page1 = mapped.slice(0, PAGE_SIZE);
      this.setData({
        alarmList: page1,
        total: mapped.length,
        hasMore: mapped.length > PAGE_SIZE,
        allLoaded: mapped.length <= PAGE_SIZE,
        _fullList: mapped,
        page: 1,
      });
    } catch (_) {
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
    this.setData({ loading: false });
  },

  loadMore() {
    const { page, _fullList = [] } = this.data;
    const nextPage = page + 1;
    const chunk = _fullList.slice(0, nextPage * PAGE_SIZE);
    this.setData({
      alarmList: chunk,
      page: nextPage,
      hasMore: chunk.length < _fullList.length,
      allLoaded: chunk.length >= _fullList.length,
    });
  },

  levelLabel(l) {
    return l === 'urgent' ? '紧急' : l === 'warning' ? '警告' : '记录';
  },
});
