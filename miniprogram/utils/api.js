/**
 * 水域溺水防控AI预警系统 - 微信小程序 API 工具
 * v2.1 — 优化版：统一 BASE_URL、增强错误处理、请求重试、离线提示
 */

/** 后端服务地址（默认与本机后端一致） */
let BASE_URL = 'https://gills-register-prescribe.ngrok-free.dev';

/** 请求重试配置 */
const RETRY_CONFIG = {
  maxRetries: 1,       // 最大重试次数
  retryDelay: 1000,    // 重试延迟(ms)
  retryMethods: ['GET'], // 仅对 GET 请求重试
};

/**
 * 更新 BASE_URL
 */
function setBaseUrl(url) {
  if (url) {
    BASE_URL = url.replace(/\/$/, '');
    console.log('[API] BASE_URL 已更新为:', BASE_URL);
  }
}

/**
 * 获取当前 BASE_URL
 */
function getBaseUrl() {
  return BASE_URL;
}

/**
 * 通用请求封装（带重试机制）
 */
function request(options, _retryCount) {
  const retryCount = _retryCount || 0;
  return new Promise((resolve, reject) => {
    const url = BASE_URL + options.path;
    console.log('[API] >>>', options.method || 'GET', url, options.body ? JSON.stringify(options.body).substring(0, 100) : '');

    wx.request({
      url: url,
      method: options.method || 'GET',
      data: options.body || {},
      header: Object.assign({ 'Content-Type': 'application/json' }, options.header || {}),
      timeout: options.timeout || 10000,
      success(res) {
        console.log('[API] <<<', res.statusCode, JSON.stringify(res.data).substring(0, 200));
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          // 登录失败也返回数据，让调用方处理
          resolve(res.data);
        } else if (res.statusCode === 503) {
          // 服务不可用，提示数据库问题
          reject({ statusCode: res.statusCode, data: res.data, msg: '服务暂时不可用，请稍后重试' });
        } else {
          reject({ statusCode: res.statusCode, data: res.data });
        }
      },
      fail(err) {
        console.error('[API] !!! 请求失败:', url, err.errMsg);

        // 判断是否需要重试
        if (
          retryCount < RETRY_CONFIG.maxRetries &&
          RETRY_CONFIG.retryMethods.indexOf(options.method || 'GET') > -1
        ) {
          console.log(`[API] 将在 ${RETRY_CONFIG.retryDelay}ms 后重试（第 ${retryCount + 1} 次）`);
          setTimeout(() => {
            request(options, retryCount + 1).then(resolve).catch(reject);
          }, RETRY_CONFIG.retryDelay);
          return;
        }

        const errMsg = err.errMsg || '';
        let msg = '无法连接服务器';
        if (errMsg.indexOf('request:fail') > -1) {
          msg += '（网络不通或后端未启动）';
        }
        if (errMsg.indexOf('url not in domain list') > -1) {
          msg += '（请在开发者工具→详情→本地设置中勾选"不校验合法域名"）';
        }
        if (errMsg.indexOf('timeout') > -1) {
          msg += '（请求超时）';
        }
        reject({ errMsg: errMsg, msg: msg });
      },
    });
  });
}

/**
 * 测试服务器连接
 * @param {string} customUrl 可选的自定义测试地址
 * @returns {Promise<{ok: boolean, msg: string, details?: object}>}
 */
function testConnection(customUrl) {
  const testUrl = (customUrl || BASE_URL).replace(/\/$/, '');
  return new Promise((resolve) => {
    console.log('[API] 测试连接:', testUrl + '/health');
    wx.request({
      url: testUrl + '/health',
      method: 'GET',
      timeout: 5000,
      success(res) {
        if (res.statusCode === 200 && res.data && res.data.status === 'ok') {
          const details = res.data;
          const dbOk = details.db === 'ok';
          let msg = '连接成功 ✓';
          if (!dbOk) {
            msg += '（但数据库不可用，请检查 MySQL）';
          }
          resolve({ ok: true, msg: msg, details: details });
        } else {
          resolve({ ok: false, msg: '服务器响应异常: HTTP ' + res.statusCode });
        }
      },
      fail(err) {
        const errMsg = err.errMsg || '';
        let msg = '无法连接服务器';
        if (errMsg.indexOf('request:fail') > -1) {
          msg += '（网络不通或后端未启动）';
        }
        if (errMsg.indexOf('url not in domain list') > -1) {
          msg += '（请在开发者工具→详情→本地设置中勾选"不校验合法域名"）';
        }
        console.error('[API] 连接测试失败:', errMsg);
        resolve({ ok: false, msg: msg });
      },
    });
  });
}

function get(path, params) {
  const options = { method: 'GET', path };
  if (params && Object.keys(params).length > 0) {
    const qs = Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    if (qs) options.path = path + '?' + qs;
  }
  return request(options);
}

function post(path, body) {
  return request({ method: 'POST', path, body: body || {} });
}

function put(path, body) {
  return request({ method: 'PUT', path, body: body || {} });
}

function del(path) {
  return request({ method: 'DELETE', path });
}

function fullUrl(path) {
  return BASE_URL + path;
}

module.exports = { get, post, put, del, fullUrl, setBaseUrl, getBaseUrl, testConnection };
