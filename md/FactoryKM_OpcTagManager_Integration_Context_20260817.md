# Factory-KM ↔ OpcTagManager Integration Context

**Date:** 2026-08-17  
**Purpose:** ใช้เป็น context กลางให้ Chat/ทีมที่พัฒนา `Factory-KM` และ `OpcTagManager` ทำงานไปในทิศทางเดียวกัน  
**Scope:** Architecture / ownership / Vault conventions / cross-module contract  
**Important:** เอกสารนี้ไม่เก็บ credential, password หรือ secret ใด ๆ

---

# 1. เป้าหมายร่วม

ต้องการให้ระบบ Alarm / OPC Tag ไม่ได้มีแค่ Tag และเสียง Alarm แต่พัฒนาเป็น Knowledge Loop ที่เรียนรู้จากการแก้ปัญหาจริงในโรงงาน

แนวคิดหลัก:

1. `OpcTagManager` ดูแลตัวตนของ OPC/Kepware Tag และ Curated Knowledge ของ Tag/Alarm
2. `Factory-KM` ใช้ Knowledge เหล่านี้ช่วยตอบ User ตอน Alarm เกิด
3. ถ้า User คุยต่อเพื่อแก้ปัญหา `Factory-KM` จะเปิด Task และติดตามจนจบ
4. เมื่อ Task จบ `Factory-KM` สรุปสิ่งที่เกิดขึ้นจริง พร้อม conversation / รูป / part ที่เปลี่ยน และบันทึกลง Vault
5. `OpcTagManager` อ่าน Feedback/History เหล่านี้กลับมาแสดงในหน้า Tag
6. ผู้ดูแล Tag สามารถ Review และ Promote ความรู้ที่ดีจากงานจริงกลับไปเป็น Knowledge Version ใหม่
7. รอบถัดไป Factory-KM จะมีทั้งวิธีแก้มาตรฐาน + ประสบการณ์จากครั้งก่อน + Manual / Drawing / Supplier / Purchase / Quotation ที่เกี่ยวข้อง

เกิดเป็น Continuous Knowledge Improvement Loop

---

# 2. Source of Truth หลัก

## 2.1 Vault

ไฟล์ Knowledge / Document / History ที่ต้องการให้ AI ของ Factory-KM อ่านในอนาคต ให้เก็บไว้ใน:

```text
D:\KM\Vault
```

ส่วนที่ `OpcTagManager` เป็นเจ้าของ ให้จำกัดขอบเขตไว้ภายใต้:

```text
D:\KM\Vault\Tags
```

Factory-KM มี filesystem-based discovery อยู่แล้ว จึงสามารถเห็น branch `Tags` ได้โดยอัตโนมัติ

## 2.2 Live / Transaction Data

ข้อมูลที่เปลี่ยนตลอด เช่น Stock On Hand, Available Qty, Reserved Qty, Store Location, Inventory movement **ไม่ควร duplicate มาเป็น source of truth ใน Vault**

อนาคตให้ query ระบบเจ้าของข้อมูลจริงผ่าน API / Linked Server / connector อื่น ๆ โดยใช้ `PartNo` / `MaterialCode` เป็น key เชื่อม

---

# 3. Canonical Identity

ตัวตนหลักของ Alarm/Tag ระหว่างสองระบบคือ:

```text
KepwarePath
```

ตัวอย่าง:

```text
LP2_SIEMENS.PACKER.FAULT.AS550_OVER_CURRENT
```

ห้ามอ้างด้วย Tag Name สั้น ๆ เพียงอย่างเดียว เพราะชื่ออาจซ้ำกันในคนละ Device/Group

`KepwarePath` ต้องถูกเก็บใน metadata ของ Tag Knowledge, Factory-KM Task, Task Summary, Conversation History, Maintenance Event, Feedback และ Resource links ที่ผูกกับ Tag

---

# 4. หน้าที่ของ OpcTagManager

`OpcTagManager` เป็นเจ้าของ:

## 4.1 Kepware / OPC Tag Identity

- Channel
- Device
- Tag Group
- Tag
- Kepware Path
- Address
- Data Type
- Scan Rate
- Access

## 4.2 Curated / Static Knowledge

หน้า Tag Knowledge ปัจจุบันมี:

- Description / Meaning
- Possible Cause
- How to Check
- Corrective Action
- Safety / Warning
- Additional Notes

ความหมายคือ **“โดยมาตรฐาน Alarm/Tag นี้คืออะไร และควรตรวจ/แก้อย่างไร”** ไม่ใช่ประวัติว่าครั้งใดครั้งหนึ่งทำอะไรจริง

## 4.3 Knowledge Versioning

Knowledge ของ Tag ต้อง versioned และไม่ overwrite ประวัติเก่า

ตัวอย่าง:

```text
D:\KM\Vault\Tags\
└─ LP2\
   └─ MIX\
      └─ Cement_FML\
         ├─ Cement_FML_20260817_075934.md
         └─ knowledge.index.json
```

`knowledge.index.json` ชี้ Active Version

---

# 5. หน้าที่ของ Factory-KM

`Factory-KM` เป็นเจ้าของ:

- Chat กับ User
- Alarm assistance
- Task creation
- Task state
- การติดตามปัญหาจนจบ
- การถาม User ว่าทำอะไรไปจริง
- การเก็บรูป/ไฟล์จากงานจริง
- การสรุป Task
- การสร้าง Maintenance History / Feedback ลง Vault

`OpcTagManager` **ไม่สร้าง Task และไม่ควบคุม Factory-KM workflow**

---

# 6. Alarm → Factory-KM Task Flow

เมื่อ Alarm เกิด:

```text
Alarm
  ↓
Factory-KM Chat
  ↓
อ่าน Curated Knowledge ของ Tag
  ↓
แสดง:
- Alarm คืออะไร
- Possible Cause
- How to Check
- Corrective Action
- Safety
- Manual / Drawing / References ในอนาคต
```

จากนั้นมี 2 ทางหลัก

## 6.1 User กด Acknowledge อย่างเดียว

```text
Alarm
  ↓
Acknowledge
  ↓
Close Task
Result = Acknowledged
```

ควรยังเก็บ record แบบบาง ๆ เพื่อให้อนาคตวิเคราะห์ได้ว่า Alarm นี้เกิดบ่อยแต่ส่วนใหญ่แค่ ACK หรือเป็นปัญหาจริง

## 6.2 User คุยกับ Factory-KM ต่อ

ทันทีที่ User เริ่มคุยแก้ปัญหาต่อ:

```text
Task = In Progress
```

AI ช่วยแนะนำตาม Knowledge และติดตามผลจนจบ

ก่อนปิด Task ต้องถาม/สรุปอย่างน้อย:

- แก้ไขได้หรือไม่
- Root Cause คืออะไร
- ทำอะไรไปบ้าง
- Reset / Adjust / Repair อะไร
- เปลี่ยน Part หรือไม่
- Part อะไร
- Part No.
- Material Code ถ้ามี
- Manufacturer / Model
- Quantity
- Serial No. ถ้ามี
- เปลี่ยนเมื่อไหร่
- ใครดำเนินการ
- มีรูปก่อน/หลัง/รูป Part หรือไม่
- Test Run แล้วผลเป็นอย่างไร
- หมายเหตุเพิ่มเติม

ก่อนบันทึกสุดท้ายควรให้ User Confirm summary

---

# 7. Factory-KM History ใน Vault

สำหรับแต่ละ Task ของ Alarm/Tag ให้แยกเป็น folder ของ Task

```text
D:\KM\Vault\Tags\
└─ LP2_SIEMENS\
   └─ PACKER\
      └─ FAULT\
         └─ AS550_OVER_CURRENT\
            ├─ AS550_OVER_CURRENT_20260817_....md
            ├─ knowledge.index.json
            │
            └─ History\
               ├─ FKM-20260817-0041\
               │  ├─ summary.md
               │  ├─ conversation.md
               │  └─ attachments\
               │     ├─ before.jpg
               │     ├─ after.jpg
               │     └─ replaced_part.jpg
               │
               └─ FKM-20260820-0012\
                  ├─ summary.md
                  └─ conversation.md
```

---

# 8. conversation.md

เก็บประวัติการคุยจริงของ Task นั้น

```markdown
---
RecordType: FactoryKMConversation
TaskId: FKM-20260817-0041
KepwarePath: LP2_SIEMENS.PACKER.FAULT.AS550_OVER_CURRENT
StartedAt: 2026-08-17T08:30:00+07:00
ClosedAt: 2026-08-17T10:42:00+07:00
---

# Factory-KM Conversation

## 08:30 User
Alarm AS550 Over Current ขึ้น ต้องตรวจอะไร

## 08:30 Factory-KM
จาก Knowledge ของ Tag แนะนำให้ตรวจ...

## 08:45 User
Reset แล้วแต่ขึ้นอีก

## 08:46 Factory-KM
ให้ตรวจสาย Motor และ...

## 09:20 User
พบว่าสาย Motor ชำรุด

## 10:15 User
เปลี่ยนสายแล้ว ทดสอบ Run ปกติ
```

ประโยชน์:

- เปิดดูย้อนหลังได้ว่าเคยลองอะไรบ้าง
- เก็บ context ที่ summary อาจตกหล่น
- AI ในอนาคตสามารถอ่าน experience จริงได้

---

# 9. summary.md

เป็น structured summary หลัง Task จบ เหมาะกับ AI retrieval มากกว่า conversation เต็ม

```markdown
---
RecordType: MaintenanceTaskSummary
TaskId: FKM-20260817-0041
KepwarePath: LP2_SIEMENS.PACKER.FAULT.AS550_OVER_CURRENT
Result: Resolved
StartedAt: 2026-08-17T08:30:00+07:00
ClosedAt: 2026-08-17T10:42:00+07:00
PartChanged: true
Manufacturer: Delta
Model: AS550
PartNo: AS550-4T0055
MaterialCode: "1000123456"
ReplacementAt: 2026-08-17T10:15:00+07:00
---

# Task Summary

## Problem
AS550 Over Current

## Root Cause
Motor cable insulation damaged

## Corrective Action
ตรวจสอบสาย Motor และเปลี่ยนสายที่ชำรุด

## Parts Changed
- Motor Cable 4x6 mm²
- Quantity: 12 m

## Result
Test Run หลังแก้ไขแล้วทำงานปกติ

## Photos
- attachments/before.jpg
- attachments/after.jpg
- attachments/replaced_part.jpg
```

---

# 10. Feedback Loop กลับ OpcTagManager

สิ่งที่ Factory-KM บันทึกจากงานจริงต้องกลับมาแสดงในหน้า Tag ของ OpcTagManager

```text
Factory-KM Feedback
────────────────────────────────

3 New / Unreviewed

17/08/2026  FKM-20260817-0041
Result: Resolved

Root Cause:
Motor cable insulation damaged

Actual Action:
- ตรวจสาย Motor
- เปลี่ยนสาย
- Reset inverter
- Test Run

Part Changed:
Yes

[View Summary]
[View Conversation]
[View Photos]
[Use in Knowledge]
[Mark Reviewed]
```

Feedback state ที่ควรมี:

```text
New
Reviewed
Promoted
Dismissed
```

---

# 11. Knowledge Promotion

Factory-KM feedback **ห้ามเขียนทับ Curated Knowledge อัตโนมัติ** เพราะเหตุการณ์หนึ่งอาจเป็นกรณีเฉพาะ

Flow:

```text
Factory-KM Task
   ↓
Feedback
   ↓
OpcTagManager แสดงให้ผู้ดูแล Tag
   ↓
Engineer / Maintenance Review
   ↓
Use in Knowledge
   ↓
Apply to Draft
   ↓
แก้ wording
   ↓
Preview
   ↓
Save Knowledge Version ใหม่
```

ควร trace ได้ว่า Knowledge Version ใดได้รับข้อมูลจาก Task ใด

---

# 12. Shared Resource Architecture

เอกสารที่ AI ควรอ่านในอนาคตต้องเก็บใน Vault เช่น:

- Manual
- Drawing
- Supplier information
- Contact
- Quotation
- Purchase documents
- Photos
- General technical documents

ไม่ควร copy file เดียวกันไป 10 Tag

ให้มี Shared Resource Library:

```text
D:\KM\Vault\Tags\
└─ _Resources\
   ├─ Manuals\
   ├─ Drawings\
   ├─ Suppliers\
   ├─ Quotations\
   ├─ Purchases\
   └─ Photos\
```

ตัวอย่าง:

```text
_Resources\
└─ Manuals\
   └─ AS550\
      ├─ AS550_Manual_20260817_081500.pdf
      ├─ AS550_Manual_20260817_081500.md
      └─ resource.index.json
```

ไฟล์จริงมี 1 ชุด แต่ link ได้หลาย Tags

---

# 13. Resource Linking

Tag สามารถอ้าง Resource ด้วย ID เช่น:

```json
{
  "manuals": ["DOC_AS550_MANUAL"],
  "drawings": ["DWG_PACKER_001"],
  "suppliers": ["SUP_DELTA"],
  "quotations": ["QT_2026_0032"]
}
```

หลักสำคัญ:

```text
1 Resource
  ↓
Many Tags
```

เพื่อไม่ให้ Manual/Drawing/Supplier/Quotation ถูก copy ซ้ำตามหลาย Tags

---

# 14. Resource Versioning / Duplicate Protection

Shared Resources ควรรองรับ:

- Versioning
- SHA-256 duplicate detection
- Link Existing Resource
- Upload New Resource
- Link to Multiple Tags
- Active version via index

Tag link ที่ `ResourceId` ไม่ link filename version โดยตรง ดังนั้น Manual เปลี่ยน Version แล้ว Tag ทั้งหมดใช้ Active Version ใหม่ได้โดยไม่แก้ link ทีละ Tag

---

# 15. Supplier / Contact

Supplier และ Contact ควรอยู่ใน Vault เพื่อให้ AI อ่านได้

```markdown
# Delta Electronics

## Supplier Information
Supplier Code: SUP_DELTA

## Contact
Name: ...
Phone: ...
Email: ...

## Products Supported
- AS550 Inverter

## Support Notes
แจ้ง Model และ Serial Number ก่อนติดต่อ
```

Supplier เดียวสามารถ link หลาย Tag / Part

---

# 16. Quotation / Purchase

Quotation และ Purchase documents ต้องเก็บ original file ใน Vault และควรมี AI-readable companion Markdown

```text
QT_AS550_20260817.pdf
QT_AS550_20260817.md
```

ตัวอย่าง Markdown:

```markdown
# Quotation AS550

Supplier: ABC Automation
Quotation No: QT-2026-0032
Quotation Date: 2026-08-17

Part: AS550 Inverter
Quantity: 2
Unit Price: 18,500 THB
Total: 37,000 THB

Original File:
QT_AS550_20260817.pdf
```

อนาคต Factory-KM จะตอบได้ เช่น เคยซื้อ AS550 กี่บาท, Supplier ไหนเคยเสนอราคา, Quotation ล่าสุดเมื่อไหร่, ราคาครั้งก่อนเท่าไร

---

# 17. Part / Equipment Identity

ควรเผื่อ field:

- Equipment Type
- Manufacturer
- Model
- PartNo
- MaterialCode
- SerialNo (เฉพาะ instance/event ถ้ามี)

ตัวอย่าง:

```text
Equipment : Inverter
Manufacturer : Delta
Model : AS550
PartNo : AS550-4T0055
MaterialCode : 1000123456
```

ใช้เชื่อม Tag → Part/Equipment → Manual / Drawing / Supplier / Quotation / Purchase History / Future Inventory Query

---

# 18. Replacement / Maintenance History

ข้อมูล “เปลี่ยน Part ล่าสุดเมื่อไหร่” เป็น Maintenance History และควรอยู่ใน Vault เพราะ Factory-KM สามารถสร้างจาก Task/Chat ได้

Factory-KM เป็นผู้สร้าง Event จากงานจริง

OpcTagManager ในอนาคตเป็นผู้ **อ่านและแสดง**

```text
Maintenance History
────────────────────────

Last Part Replacement:
17/08/2026 10:15

Part:
Delta AS550
AS550-4T0055

Reason:
Over Current / Cable damage

Task:
FKM-20260817-0041

[View Summary]
[View Conversation]
[View Photos]
[View Full History]
```

---

# 19. Stock / Inventory — Future Only

Stock ไม่อยู่ใน scope ปัจจุบัน

อนาคต:

```text
OpcTagManager / Factory-KM
       ↓
MaterialCode / PartNo
       ↓
Inventory API
หรือ Linked Server
       ↓
On Hand
Available
Location
```

ห้ามสร้าง Stock master ซ้ำใน OpcTagManager ถ้ามีระบบเจ้าของข้อมูลอยู่แล้ว

---

# 20. Ownership Boundary สรุป

## OpcTagManager

```text
Tag Identity
Kepware Configuration
Curated Alarm Knowledge
Knowledge Versioning
Shared Resource Linking
Feedback Review
Knowledge Promotion
Maintenance History Reader (future)
```

## Factory-KM

```text
Chat
Alarm Assistance
Task Management
Task Follow-up
User Interaction
Task Close / Acknowledge
Conversation Capture
Task Summary
Photos / Attachments from actual work
Maintenance Event Creation
Factory-KM Feedback into Vault
```

## External Systems

```text
Inventory / ERP / Store
Live Stock
Reserved Qty
Location
Transaction Data
```

---

# 21. Core Principle

> **Factory-KM เก็บ “สิ่งที่เกิดขึ้นจริง”**  
> **OpcTagManager ดูแล “สิ่งที่ควรใช้เป็นความรู้มาตรฐาน”**

และทั้งสองระบบใช้ `Vault + KepwarePath` เป็นสะพานเชื่อมกัน

---

# 22. Suggested Roadmap ฝั่ง OpcTagManager

ปัจจุบัน Phase 4.3 มี Versioned Tag Knowledge แล้ว

```text
Phase 4.4  Shared Resource Architecture
Phase 4.5  Manual / Drawing / Document Upload
Phase 4.6  Supplier / Contact
Phase 4.7  Quotation / Purchase
Phase 4.8  Maintenance History Reader
Phase 4.9  Factory-KM Feedback Reader & Knowledge Promotion
Future     Stock / ERP API or Linked Server
```

ลำดับย่อยอาจปรับตาม implementation จริง แต่ ownership boundary ด้านบนควรรักษาไว้

---

# 23. สิ่งที่ Factory-KM ควรเตรียมเพื่อ Integration

1. Task ต้องมี `TaskId`
2. Task ที่มาจาก Alarm ต้องเก็บ `KepwarePath`
3. ACK-only task ต้องมีสถานะชัดเจน
4. Task ที่ User คุยต่อ ต้องเก็บ conversation
5. ก่อน Close ต้องสรุป actual work
6. ถ้ามี Part change ต้องเก็บ Part identity เท่าที่ User ทราบ
7. รองรับ attachments/photos
8. เขียน `summary.md`
9. เขียน `conversation.md`
10. เก็บใต้ `History\<TaskId>\` ของ Tag ที่ถูกต้อง
11. อย่าแก้ Curated Knowledge ของ OpcTagManager โดยตรง
12. Feedback ต้องถูก review/promote จาก OpcTagManager ก่อนกลายเป็น Knowledge มาตรฐาน

---

# 24. Integration Contract ที่สำคัญที่สุด

ขั้นต่ำ metadata ที่ควรแลกกัน:

```text
TaskId
KepwarePath
StartedAt
ClosedAt
Result
Problem
RootCause
CorrectiveAction

PartChanged
Manufacturer
Model
PartNo
MaterialCode
Quantity
ReplacementAt

Attachments
```

สิ่งที่จำเป็นที่สุดคือ `KepwarePath` เพราะเป็น canonical link กลับไปยัง Alarm/Tag

---

# 25. End State ที่ต้องการ

ในอนาคต User ถาม Factory-KM:

> AS550 Over Current ต้องแก้ยังไง และครั้งก่อนเคยเกิดไหม?

AI สามารถรวม:

- Curated Knowledge จาก OpcTagManager
- Manual
- Drawing
- Supplier
- Quotation/Purchase
- Factory-KM Task History
- Conversation History
- Previous Root Causes
- Previous Parts Changed

แล้วตอบได้

ถ้าถามต่อ:

> ถ้าเสียมีอะไหล่ไหม?

จึงค่อยไป query Inventory/ERP แบบ live ผ่าน API / Linked Server

---

# 26. Instruction for the Factory-KM Development Chat

อ่านข้อความนี้เป็น architecture/context กลางก่อนแก้ Factory-KM

**อย่า implement งานของ OpcTagManager ซ้ำ**

ให้ Factory-KM รับผิดชอบ Task/Conversation/Maintenance Event ตาม boundary ที่ระบุ

ถ้ามี requirement ใหม่ที่กระทบ schema หรือ folder structure ของ `D:\KM\Vault\Tags` ให้รักษา:

- `KepwarePath` เป็น canonical identity
- version/history ต้องไม่ overwrite
- original files ต้องอยู่ใน Vault หากต้องการให้ AI อ่านในอนาคต
- shared resource ต้องไม่ duplicate file ไปตามหลาย Tags
- Stock เป็น external live data และอยู่นอก scope ปัจจุบัน
