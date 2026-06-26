// pages/devices/devices.js
const api = require('../../utils/api');

Page({
  data: {
    deviceList: [],
    loading: false,
    showAddForm: false,
    // 新增设备表单
    form: {
      name: '',
      device_id: '',
      location: '',
      ip_address: '',
      status: 'online',
    },
    statusOptions: ['online', 'offline'],
    statusLabels: ['在线', '离线'],
    statusIndex: 0,
    saving: false,
  },

  onLoad() {
    const app = getApp();
    if (!app.globalData.userInfo) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this.loadDevices();
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 2 });
    }
  },

  onPullDownRefresh() {
    this.loadDevices().finally(() => wx.stopPullDownRefresh());
  },

  async loadDevices() {
    this.setData({ loading: true });
    try {
      const list = await api.get('/api/devices');
      if (Array.isArray(list)) {
        this.setData({
          deviceList: list.map(d => ({
            ...d,
            statusLabel: d.status === 'online' ? '在线' : '离线',
            lastOnlineShort: d.last_online ? d.last_online.substring(0, 16) : '--',
          })),
        });
      }
    } catch (_) {
      wx.showToast({ title: '加载失败', icon: 'none' });
    }
    this.setData({ loading: false });
  },

  toggleAddForm() {
    this.setData({
      showAddForm: !this.data.showAddForm,
      form: { name: '', device_id: '', location: '', ip_address: '', status: 'online' },
      statusIndex: 0,
    });
  },

  onFormInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [`form.${field}`]: e.detail.value });
  },

  onStatusChange(e) {
    const idx = e.detail.value;
    this.setData({
      statusIndex: idx,
      'form.status': this.data.statusOptions[idx],
    });
  },

  async saveDevice() {
    if (!this.data.form.name.trim()) {
      wx.showToast({ title: '请输入设备名称', icon: 'none' });
      return;
    }
    this.setData({ saving: true });
    try {
      const form = this.data.form;
      const data = await api.post('/api/devices', {
        name: form.name.trim(),
        device_id: form.device_id.trim() || null,
        location: form.location.trim() || null,
        ip_address: form.ip_address.trim() || null,
        status: form.status,
      });
      if (data && data.success) {
        wx.showToast({ title: '添加成功', icon: 'success' });
        this.setData({ showAddForm: false });
        this.loadDevices();
      } else {
        wx.showToast({ title: (data && data.detail) || '添加失败', icon: 'none' });
      }
    } catch (_) {
      wx.showToast({ title: '请求失败', icon: 'none' });
    }
    this.setData({ saving: false });
  },

  async deleteDevice(e) {
    const { id, name } = e.currentTarget.dataset;
    const confirmed = await new Promise(resolve => {
      wx.showModal({
        title: '确认删除',
        content: `确定要删除设备「${name}」吗？`,
        confirmColor: '#e74c3c',
        success: res => resolve(res.confirm),
      });
    });
    if (!confirmed) return;
    try {
      const data = await api.del(`/api/devices/${id}`);
      if (data && data.success) {
        wx.showToast({ title: '已删除', icon: 'success' });
        this.loadDevices();
      }
    } catch (_) {
      wx.showToast({ title: '删除失败', icon: 'none' });
    }
  },

  async toggleStatus(e) {
    const { id, status } = e.currentTarget.dataset;
    const newStatus = status === 'online' ? 'offline' : 'online';
    try {
      await api.put(`/api/devices/${id}`, { status: newStatus });
      wx.showToast({ title: `已切换为${newStatus === 'online' ? '在线' : '离线'}`, icon: 'success' });
      this.loadDevices();
    } catch (_) {
      wx.showToast({ title: '操作失败', icon: 'none' });
    }
  },
});
