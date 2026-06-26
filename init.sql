-- ============================================================
-- 水域溺水防控AI预警系统 v3.0 - 数据库初始化脚本
-- 数据库：drowning_alarm
-- MySQL 5.7+
-- ============================================================

CREATE DATABASE IF NOT EXISTS drowning_alarm
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE drowning_alarm;

-- ── 用户表 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id           INT PRIMARY KEY AUTO_INCREMENT,
    phone        VARCHAR(20)  NOT NULL UNIQUE COMMENT '手机号（登录账号）',
    password     VARCHAR(100) NOT NULL        COMMENT '密码',
    role         VARCHAR(20)  DEFAULT 'user'  COMMENT '角色：admin/user',
    nickname     VARCHAR(50)  DEFAULT ''      COMMENT '昵称',
    create_time  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认管理员账号：13800138000 / 123456
INSERT IGNORE INTO users (phone, password, role, nickname) VALUES
  ('13800138000', '123456', 'admin', '系统管理员');

-- ── 摄像头表（v3.0 新增）──────────────────────────────────
CREATE TABLE IF NOT EXISTS cameras (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    camera_id       VARCHAR(50)  UNIQUE NOT NULL COMMENT '摄像头编号',
    name            VARCHAR(100) NOT NULL         COMMENT '摄像头名称',
    source          VARCHAR(255) NOT NULL         COMMENT '视频源（索引/RTSP/文件路径）',
    location        VARCHAR(255) DEFAULT ''        COMMENT '安装位置',
    status          VARCHAR(20)  DEFAULT 'offline' COMMENT '状态：online/offline/error',
    resolution      VARCHAR(20)  DEFAULT ''        COMMENT '分辨率',
    last_frame_time DATETIME                      COMMENT '最后帧时间',
    create_time     DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认摄像头
INSERT IGNORE INTO cameras (camera_id, name, source, location, status) VALUES
  ('CAM-001', '1号摄像头', '0', '北区', 'offline'),
  ('CAM-002', '2号摄像头', '1', '南区', 'offline');

-- ── 报警记录表 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alarms (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    time        DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '报警时间',
    location    VARCHAR(255) DEFAULT '未知位置'         COMMENT '报警位置',
    message     TEXT                                    COMMENT '报警描述',
    level       VARCHAR(20)  DEFAULT 'warning'          COMMENT '级别：urgent/warning/info',
    status      VARCHAR(20)  DEFAULT 'unread'           COMMENT '状态：unread/read',
    image_path  TEXT                                    COMMENT '截图路径',
    INDEX idx_time (time),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 设备表 ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    name        VARCHAR(100) NOT NULL                   COMMENT '设备名称',
    device_id   VARCHAR(50)  UNIQUE                     COMMENT '设备编号',
    device_type VARCHAR(20)  DEFAULT 'camera'           COMMENT '类型：camera/sensor/other',
    location    TEXT                                    COMMENT '安装位置',
    ip_address  VARCHAR(50)                             COMMENT 'IP 地址',
    status      VARCHAR(20)  DEFAULT 'online'           COMMENT '状态：online/offline',
    camera_id   VARCHAR(50)  DEFAULT NULL               COMMENT '关联摄像头',
    last_online DATETIME     DEFAULT CURRENT_TIMESTAMP  COMMENT '最近在线时间',
    create_time DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认示例设备
INSERT IGNORE INTO devices (name, device_id, device_type, location, ip_address, status, camera_id) VALUES
  ('1号摄像头', 'CAM-001', 'camera', '北区', '192.168.1.101', 'online', 'CAM-001'),
  ('2号摄像头', 'CAM-002', 'camera', '南区', '192.168.1.102', 'online', 'CAM-002');

-- ── 系统设置表 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    key_name    VARCHAR(100) UNIQUE NOT NULL COMMENT '配置键',
    value       TEXT                        COMMENT '配置值',
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP
                         ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认系统配置
INSERT IGNORE INTO settings (key_name, value) VALUES
  ('sensitivity', '80'),
  ('sound_alarm', 'true'),
  ('push_notify', 'true'),
  ('auto_record', 'false'),
  ('server_url',  'http://127.0.0.1:8000');
