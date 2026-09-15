# OT Network Design --- Kepware Server with 5 Dedicated LAN Ports

## 1. วัตถุประสงค์

ใช้ Kepware Server เชื่อมต่อเครือข่ายเครื่องจักร OT จำนวน 5 วงผ่าน LAN Port
แยกวงละ 1 Port เพื่ออ่านข้อมูล PLC โดยตรง

-   LAN1 → MC1
-   LAN2 → MC2
-   LAN3 → MC3
-   LAN4 → MC8
-   LAN5 → DP (DP1 และ DP2 อยู่ในวง OT เดียวกัน)

แต่ละ Machine Network แยกจากกัน ดังนั้น PLC ที่อยู่คนละวงสามารถใช้ IP Address
ซ้ำกันได้ ตราบใดที่ภายใน Machine Network เดียวกันไม่มี IP ซ้ำ

## 2. Topology

``` text
                    KEPWARE SERVER
               +----------------------+
MC1 ---------->| LAN1                 |
MC2 ---------->| LAN2                 |
MC3 ---------->| LAN3      Kepware    |
MC8 ---------->| LAN4                 |
DP1 + DP2 ---->| LAN5                 |
               +----------------------+
```

แต่ละ LAN Port เชื่อมกับ Machine Network ของตัวเองโดยตรง ไม่ใช้ Port
เดียวร่วมกันระหว่าง MC

## 3. ตัวอย่าง IP

  Machine Network   Kepware NIC   PLC ตัวอย่าง
  ----------------- ------------- -------------------------------------
  MC1               LAN1          192.168.0.1, .2, .3
  MC2               LAN2          192.168.0.1, .2, .3
  MC3               LAN3          192.168.0.1, .2, .3
  MC8               LAN4          192.168.0.1, .2, .3
  DP1 + DP2         LAN5          ใช้ IP เดิมของวง DP โดยห้ามซ้ำกันภายในวง

ตัวอย่าง `192.168.0.1` สามารถมีอยู่ใน MC1, MC2, MC3 และ MC8 ได้ เพราะอยู่คนละ
Machine Network แต่ห้ามมี PLC สองตัวใช้ IP เดียวกันภายใน MC เดียวกัน

## 4. การอ่านข้อมูลด้วย Kepware

สำหรับ Siemens TCP/IP Ethernet หรือ Driver ที่เกี่ยวข้อง ให้แยก Kepware Channel
ตาม MC และกำหนด Network Adapter ให้ตรงกับ NIC ของวงนั้น เช่น

``` text
Channel MC1 -> Network Adapter LAN1 -> PLC 192.168.0.1
Channel MC2 -> Network Adapter LAN2 -> PLC 192.168.0.1
Channel MC3 -> Network Adapter LAN3 -> PLC 192.168.0.1
Channel MC8 -> Network Adapter LAN4 -> PLC 192.168.0.1
```

แม้ Destination IP เหมือนกัน แต่แนวทางนี้ตั้งใจให้ Kepware ส่ง Connection ออกคนละ
Network Adapter ไปยังคนละ Physical Machine Network

## 5. ข้อควรระวังสำคัญ

การมี subnet เดียวกันซ้ำอยู่บนหลาย NIC ของ Windows เป็นกรณีพิเศษ ต้องทดสอบบน
Server จริงอย่างรอบคอบ เพราะ Windows routing table อาจมีหลาย route ไป
destination subnet เดียวกัน การแยกสายทางกายภาพเพียงอย่างเดียวไม่ได้รับประกันว่า
application ทุกตัวจะเลือก NIC ถูกเสมอ

ดังนั้น Kepware Channel ต้องสามารถ bind/select Network Adapter ของวงนั้นได้จริง
และต้องทดสอบพร้อมกันทุก NIC ก่อน Commissioning

แนวทางตั้งค่าที่ควรใช้:

-   ตั้งชื่อ NIC ชัดเจน เช่น `OT_MC1`, `OT_MC2`, `OT_MC3`, `OT_MC8`, `OT_DP`
-   Machine-side NIC ไม่ตั้ง Default Gateway หากไม่จำเป็น
-   ไม่ทำ Windows Network Bridge หรือ Internet Connection Sharing ระหว่าง
    MC
-   ไม่เปิด IP forwarding/routing ระหว่าง Machine Networks โดยไม่จำเป็น
-   บันทึก NIC, MAC Address, IP, สาย และ MC ที่เชื่อมต่อใน As-Built
-   Kepware Channel ทุกวงต้องระบุ Network Adapter ให้ชัดเจน

## 6. กฎเรื่อง IP ซ้ำ

**ทำได้ --- ซ้ำข้ามวง**

``` text
MC1 : PLC01 = 192.168.0.1
MC2 : PLC01 = 192.168.0.1
MC3 : PLC01 = 192.168.0.1
MC8 : PLC01 = 192.168.0.1
```

**ทำไม่ได้ --- ซ้ำภายในวงเดียวกัน**

``` text
MC1 : PLC01 = 192.168.0.1
MC1 : PLC02 = 192.168.0.1  <-- IP Conflict
```

## 7. ข้อดีในมุม OT

-   รักษา IP Address และ Hardware Configuration เดิมของ PLC
-   ไม่ต้อง Commissioning PLC ใหม่เพียงเพื่อเปลี่ยน IP Plan
-   ไม่ต้องเพิ่ม Default Gateway ให้ PLC เพื่อให้ Kepware อ่านข้อมูล
-   ไม่ต้องบังคับ PLC เดิมเข้าสู่ VLAN/L3 architecture
-   แต่ละ MC แยกเป็น fault domain ของตัวเอง
-   ลดความซับซ้อนในการ Maintenance และ Emergency Recovery
-   เหมาะกับ Installed Base ที่มี PLC เดิมจำนวนมากและอาจไม่มี Software/Project
    สำหรับแก้ Hardware Configuration
-   ช่างหรือผู้รับเหมาสามารถไล่ปัญหาทีละ Machine Network ได้ง่ายกว่า

## 8. Acceptance Test ก่อนใช้งานจริง

1.  ทดสอบแต่ละ NIC/MC แยกทีละวง
2.  Enable LAN1--LAN5 พร้อมกัน
3.  ตรวจสอบว่าแต่ละ Kepware Channel อ่าน PLC จาก MC ที่ถูกต้อง
4.  ทดสอบ PLC IP เดียวกันในคนละ MC พร้อมกัน
5.  ตรวจสอบ Source Interface/Connection ของ Server
6.  Restart Kepware Runtime แล้วทดสอบใหม่
7.  Restart Windows Server แล้วทดสอบใหม่
8.  ถอดสาย MC หนึ่งวงและยืนยันว่า MC อื่นยังอ่านได้
9.  Backup Kepware configuration และจัดทำ As-Built หลังผ่านการทดสอบ

## 9. สรุป

Kepware Server ใช้ LAN 5 Port แยกสำหรับ MC1, MC2, MC3, MC8 และ DP โดยแต่ละ
Machine Network เป็นอิสระจากกัน จึงสามารถมี PLC IP ซ้ำข้าม MC ได้ แต่ IP
ภายในวงเดียวกันต้องไม่ซ้ำ

หัวใจสำคัญคือ **Kepware ต้อง bind/select Network Adapter ให้ถูกวง**
และต้องยืนยันพฤติกรรม routing/interface ของ Windows Server
ด้วยการทดสอบจริงเมื่อหลาย NIC ใช้ subnet ซ้ำกัน

> **Design Principle:** รักษา Machine Network เดิมให้เรียบง่ายและเป็นอิสระ
> แล้วให้ Kepware เป็นฝ่ายเข้าไปอ่านข้อมูลผ่าน NIC เฉพาะของแต่ละวง แทนการแก้
> Network Configuration ของ PLC เดิมทั้งโรงงาน
