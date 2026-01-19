================================================================================
                    RDT PRO - DEPO VE STOK TAKİP SİSTEMİ
                          KULLANIM VE TEKNİK KILAVUZ
================================================================================

1. GENEL BAKIŞ
--------------------------------------------------------------------------------
RDT Pro, modern işletmelerin depo ve envanter yönetim süreçlerini dijitalleştirmek,
hızlandırmak ve hata payını minimize etmek için geliştirilmiş, yüksek performanslı
bir masaüstü uygulamasıdır. Python tabanlı olup, kullanıcı dostu CustomTkinter
arayüzü ve güvenilir SQLite veritabanı altyapısını kullanır.

2. TEMEL MODÜLLER VE ÖZELLİKLER
--------------------------------------------------------------------------------
A. DASHBOARD (GÖSTERGE PANELİ)
   - Toplam malzeme çeşidi, toplam stok adedi ve kritik seviyedeki ürün sayısı.
   - Belirli tarih aralıklarına göre stok hareket grafikleri (Matplotlib entegrasyonu).
   - Gerçek zamanlı veri görselleştirme.

B. MEVCUT STOK LİSTESİ
   - Tüm malzemelerin ID, Ad, Konum, Stok ve Birim bilgilerini içeren detaylı tablo.
   - KRİTİK STOK TAKİBİ: Stok miktarı 3'ün altına düşen ürünler animasyonlu renk
     geçişleriyle kullanıcıyı uyarır.
   - RESİM ÖNİZLEME: Fareyle malzeme üzerine gelindiğinde ürün resmi otomatik açılır.
   - GELİŞMİŞ KONUM SİSTEMİ: Malzemenin tam hiyerarşik konumu 
     (Örn: KAT 1 > BÖLGE A > RAF 5) tek satırda görünür.

C. MALZEME GİRİŞ / ÇIKIŞ (CHECKOUT & ENTRY)
   - Hızlı malzeme hareketi kaydı.
   - Çıkan malzemenin kime (Personel/Takım) teslim edildiği bilgisi.
   - Birim fiyat ve açıklama desteği.
   - Teslim Tesellüm Tutanağı: Malzeme çıkışında otomatik PDF rapor oluşturma.

D. İŞLEM GEÇMİŞİ (HISTORY)
   - Yapılan tüm giriş ve çıkışların kronolojik listesi.
   - Filtreleme ve arama özellikleri.

E. RAPORLAMA VE ANALİZ
   - Excel Aktarımı: Tüm listeyi tek tıkla Excel formatında dışa aktarma.
   - Excel'den Yükleme: Binlerce veriyi saniyeler içinde Excel'den sisteme alma.
   - PDF Raporları: Profesyonel görünümlü teslimat belgeleri.

3. GELİŞMİŞ DEPO LOKASYON YÖNETİMİ
--------------------------------------------------------------------------------
Sistem, statik raf numaraları yerine dinamik bir hiyerarşi sunar:
- Esnek Yapı: Kat, Bölge, Raf ve Bölüm/Göz seviyeleri isteğe göre aktif edilir.
- Arama Desteği: Binlerce lokasyon arasından isimle hızlı seçim yapabilme.
- Görsel İkonlar: 🏢 Kat, 🚧 Bölge, 🗄️ Raf, 📦 Bölüm ikonlarıyla kolay ayrım.
- Düzenleme Kolaylığı: Malzeme kartı içinden kalem butonuyla anında konum değişimi.

4. SİSTEMİN DİĞER AVANTAJLARI
--------------------------------------------------------------------------------
- GERİ AL / YİNELE (UNDO/REDO): Hatalı silme veya düzenlemeleri anında geri alma.
- OTOMATİK YEDEKLEME: Veritabanı her açılışta ve belirli aralıklarla yedeklenir.
- SINIRSIZ STOK: Sarf malzemeleri için "Sınırsız" işareti koyabilme.
- MODÜLER YAPI: Yeni özellikler (SKT Takibi, Maliyet Analizi vb.) ana koda 
  müdahale etmeden dinamik olarak yüklenebilir.
- TEMA DESTEĞİ: Göz yormayan Dark (Karanlık) ve Modern Light (Aydınlık) modları.

5. TEKNİK ALTYAPI VE VERİ YOLU
--------------------------------------------------------------------------------
- Dil: Python 3.x
- Arayüz: CustomTkinter (Modern UI Components)
- Veritabanı: SQLite (İlişkisel Veri Modeli)
- Veri Saklama: C:\Users\User\Desktop\RDT Pro\RDT_Pro_Data
- Rapor Çıktıları: RDT_Pro_Data\Raporlar

================================================================================
RDT Soft tarafından 2026 versiyonu için optimize edilmiştir.
================================================================================

================================================================================
                    RDT PRO - EK MODÜLLER VE FONKSİYONLAR
                             TEKNİK DETAY KILAVUZU
================================================================================

RDT Pro, modüler yapısı sayesinde ihtiyaca göre genişletilebilir. Aşağıda sistemde
yüklü olan ve deponun gücüne güç katan ek modüllerin detayları yer almaktadır.

1. KONUM YÖNETİMİ MODÜLÜ (Konum_Yonetimi)
--------------------------------------------------------------------------------
Deponun fiziksel yapısını dijital bir ağaç yapısına dönüştürür.
- Hiyerarşik Yapı: Kat > Bölge/Koridor > Raf > Bölüm/Göz kırılımları sunar.
- Özelleştirme: Hangi seviyelerin aktif olacağı "Yapılandırma" sekmesinden seçilir.
- Görsel Yardımcılar: Her seviye için özel ikonlar (🏢, 🚧, 🗄️, 📦) kullanılır.
- Kapasite Takibi: Her bölüme maksimum kapasite tanımlanabilir.

2. TOPLU İŞLEM MODÜLÜ (Toplu_Islemler)
--------------------------------------------------------------------------------
Yüzlerce ürünü saniyeler içinde yönetmenizi sağlar.
- Çoklu Seçim: Stok listesinde "Seç" sütunu açarak ☑/☐ kutucuklarıyla seçim yapılır.
- Toplu Güncelleme: Seçilen tüm ürünlere tek seferde ortak bir konum atanabilir.
- Toplu Stok Değişimi: Seçilen tüm ürünlerin stoğu tek tıkla artırılır veya azaltılır.
- İşlem Güvenliği: "BEGIN TRANSACTION" yapısı sayesinde, bir üründe hata oluşursa 
  (Örn: Yetersiz stok) hiçbir değişiklik kaydedilmez (Rollback).

3. İADE VE HASAR YÖNETİMİ (Iade_ve_Hasar)
--------------------------------------------------------------------------------
Çıkışı yapılan ürünlerin geri dönüş ve zayiat süreçlerini yönetir.
- İade Sistemi: Sahadan dönen sağlam ürünler stoğa geri alınır ve teslim eden 
  bilgisiyle kaydedilir.
- Hasar/Fire Kaydı: Kırılan, bozulan veya kaybolan ürünler stoktan düşülür.
- Neden Takibi: Her hasar kaydı için bir "Neden" (Kırılma, Bozulma vb.) girilir.
- Dashboard Entegrasyonu: Günlük toplam iade ve hasar sayıları ana ekranda özetlenir.

4. SKT TAKİP MODÜLÜ (SKT_Takibi)
--------------------------------------------------------------------------------
Son kullanma tarihi olan ürünlerin takibini yapar.
- Erken Uyarı: Ayarlardan belirlenen gün sayısı (Örn: 30 gün) kala sistem uyarı verir.
- Renkli Kodlama: Tarihi yaklaşan ürünler listede dikkat çekici renklerle vurgulanır.
- Dashboard Widget: En yakın tarihli 5 ürünü ana ekranda listeler.

5. MALİYET ANALİZİ MODÜLÜ (Maliyet_Analizi)
--------------------------------------------------------------------------------
Deponun finansal değerini gerçek zamanlı hesaplar.
- Ortalama Maliyet: Ürünlerin giriş fiyatlarına göre otomatik maliyet hesaplar.
- Toplam Envanter Değeri: Depodaki tüm malların toplam TL karşılığını gösterir.
- Harcama Grafikleri: Hangi dönemde ne kadar satın alma yapıldığını analiz eder.

6. TEDARİKÇİ KALİTE MODÜLÜ (Tedarikci_Kalitesi)
--------------------------------------------------------------------------------
Satın alma süreçlerini verimlileştirir.
- Puanlama Sistemi: Tedarikçilere 1-5 arası performans puanı verilebilir.
- En İyi Tedarikçi: En yüksek puanlı ve en güvenilir tedarikçileri öne çıkarır.
- İletişim Rehberi: Tedarikçi telefon ve e-posta bilgilerini merkezi olarak tutar.

7. KRİTİK STOKLAR MODÜLÜ (Kritik_Stoklar)
--------------------------------------------------------------------------------
Stokta tükenmek üzere olan ürünleri asla kaçırmamanızı sağlar.
- Otomatik Animasyon: Stok 3'ün altına düştüğünde satır canlı renklerle yanıp söner.
- Acil Liste: Kritik seviyedeki tüm ürünleri tek bir ekranda raporlar.

================================================================================
RDT Soft - 2026 Modüler Depo Çözümleri
Modül satın almak için mail üzerinden iletişime geçiniz: teknohaber2018@gmail.com
================================================================================
