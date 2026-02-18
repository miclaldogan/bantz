# Classroom — Google Classroom Integration

## Triggers (TR / EN)

- "derslerim neler", "ödevlerim ne durumda", "classroom'a bak", "teslim durumu"
- "my courses", "list assignments", "homework status", "classroom check"

## Tools

| Tool | Açıklama | Risk |
|------|----------|------|
| `google.classroom.courses` | Aktif/arşiv ders listesi | SAFE |
| `google.classroom.coursework` | Bir dersin ödev/sınav listesi | SAFE |
| `google.classroom.submissions` | Teslim durumları (teslim edildi, geç, not) | SAFE |

## Instructions

### Akış
1. Kullanıcı "derslerimi göster" derse → `google.classroom.courses` çağır
2. "X dersinin ödevleri" → course_id'yi bul → `google.classroom.coursework`
3. "ödev durumum" → `google.classroom.submissions` ile teslim durumunu raporla

### Kurallar
- Tüm araçlar **read-only** — veri değiştirmez
- OAuth scope: `classroom.courses.readonly`, `classroom.coursework.me`
- Teslim edilmemiş ödevler **uyarı** ile gösterilmeli
- Geç teslimler **kırmızı bayrak** ile işaretlenmeli

## Slot Extraction

| Slot | Tip | Kaynak |
|------|-----|--------|
| `course_name` | string | kullanıcı ifadesi → course_id'ye eşle |
| `state` | enum | ACTIVE / ARCHIVED (default: ACTIVE) |
| `course_id` | string | önceki courses sorgusundan |

## Proactive

- Günlük program (daily_program) ile entegre — yaklaşan ödev tarihleri hatırlat
- Teslim edilmemiş ödev varsa sidebar'da uyarı göster
