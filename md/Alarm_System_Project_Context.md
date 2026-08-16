
# Alarm System Project Context

## Project Overview

Alarm System เป็นระบบตรวจสอบและแจ้งเตือน Alarm สำหรับโรงงาน

ระบบพัฒนาด้วย Python Flask และมีแผนเชื่อมต่อ OPC-UA เพื่อรับข้อมูล Alarm จาก PLC และอุปกรณ์ภาคสนาม

เป้าหมายคือสร้างระบบที่ดูแลรักษาง่าย ขยายต่อได้ และรองรับการใช้งานจริงในโรงงาน

---

## Repository

GitHub Repository

alarm_system

---

## Current Technology Stack

### Backend

- Python
    
- Flask
    

### Frontend

- HTML
    
- CSS
    
- JavaScript
    

### Source Control

- Git
    
- GitHub
    

---

## Development Environment

### Local Development Machine

ใช้สำหรับ

- พัฒนาโปรแกรม
    
- Refactor Code
    
- พัฒนา UI
    
- ทดสอบ Logic
    

ข้อจำกัด

- ไม่มี OPC-UA Server จริง
    
- ไม่มี PLC จริง
    
- ไม่มี Alarm Source จริง
    
- อาจไม่มีไฟล์เสียงจริง
    

---

### Production Server

ใช้สำหรับ

- เชื่อมต่อ OPC-UA จริง
    
- รับ Alarm จริง
    
- ทดสอบเสียงแจ้งเตือนจริง
    
- Deploy Production
    

---

## Current Project Structure

Current project files

- alarm_list.py
    
- config/config.py
    
- templates/*
    
- static/*
    

---

## Future Architecture

ควรแยก Layer ให้ชัดเจน

### Web Layer

Flask Routes  
UI Rendering  
REST API

### Alarm Layer

Alarm Logic  
Alarm State  
Alarm Priority

### OPC-UA Layer

Connect  
Reconnect  
Subscription  
Data Processing

### Audio Layer

Play Alarm  
Stop Alarm  
Mute Alarm

### Configuration Layer

System Configuration  
Environment Variables

---

## Development Rules

Before making changes

1. Understand existing code
    
2. Explain findings
    
3. Propose plan
    
4. Wait for approval
    

Do not perform large refactors without approval.

Keep existing functionality working.

---

## Current Goal

1. Review current codebase
    
2. Improve maintainability
    
3. Prepare OPC-UA integration
    
4. Prepare alarm audio system
    
5. Improve project structure
    

---

## What AI Agents Should Do First

When entering this project

1. Read all source files
    
2. Explain current architecture
    
3. Identify risks
    
4. Suggest improvements
    
5. Create refactoring roadmap
    

Do not modify code immediately.

Always explain before changing code.