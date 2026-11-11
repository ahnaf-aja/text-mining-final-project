# Analisis Dinamika Topik Pemberitaan Generative AI pada Media Online Indonesia Menggunakan BERTopic

Final Project **DTSC6008001 – Text Mining**, BINUS University — Group 4

- 2802394443 – Shaquille Ahnaf Fawwaz
- 2802402073 – Reynard Mulia

Proyek text mining end-to-end pada berita bertema AI / Generative AI dari **detik.com**,
**cnnindonesia.com**, dan **liputan6.com** (Desember 2022 – Oktober 2026, 6.714 artikel bersih, 5 domain berita):

```
Scraping → Cleaning → Preprocessing → Klasifikasi 5 domain (BiLSTM vs IndoBERT)
→ Klasifikasi akhir → BERTopic per kelas + dinamika topik → Ringkasan topic-aware per kelas → ROUGE
```

## Isi repositori

| File | Isi |
|---|---|
| `Group4_Scraping.py` | Scraper Detik (halaman pencarian per kata kunci × bulan), CNN Indonesia (API pencarian + halaman tag), dan Liputan6 (halaman tag) |
| `Group4_01_DataCollection.ipynb` | Task 1 – sumber data, metode scraping, periode, jumlah data, pemilihan 5 domain (label) |
| `Group4_02_Preprocessing_EDA.ipynb` | Task 2 – cleaning, EDA, preprocessing dua jalur beserta justifikasinya |
| `Group4_03_Classification_BiLSTM_IndoBERT.ipynb` | Task 3 – BiLSTM vs IndoBERT, hyperparameter tuning, evaluasi, analisis kesalahan |
| `Group4_04_TopicModelling_BERTopic.ipynb` | Task 4 – BERTopic per kelas, pemilihan jumlah topik, nama topik, dokumen representatif, dinamika topik |
| `Group4_05_TopicAwareSummarization.ipynb` | Task 5 – ringkasan sadar-topik per kelas, evaluasi ROUGE, verifikasi cakupan topik |
| `scraped/` | hasil mentah scraping (JSONL): indeks pencarian Detik, isi artikel Detik, artikel CNN, indeks dan artikel Liputan6 |
| `detik_selected.csv` | daftar URL Detik yang diunduh isinya |
| `raw_dataset.csv` | gabungan artikel mentah ketiga portal (sebelum cleaning dan penyaringan relevansi AI) |
| `dataset_clean.csv` | dataset bersih (teks alami + token hasil preprocessing + label domain) |
| `dataset_classified.csv` | dataset + kelas hasil prediksi model terbaik (IndoBERT) |
| `dataset_topics.csv` | dataset + topik BERTopic per dokumen |
| `topic_info.csv` | daftar topik per kelas: nama, kata kunci, jumlah dokumen, dokumen representatif |
| `topic_summaries.csv` | ringkasan per kelas per topik (hasil akhir) |
| `results/` | tabel metrik (tuning, evaluasi klasifikasi, kualitas topik, ROUGE, uji statistik) |
| `figures/` | semua grafik |

## Menjalankan

```bash
python -m venv .venv
.venv/Scripts/pip install torch --index-url https://download.pytorch.org/whl/cu124
.venv/Scripts/pip install -r requirements.txt
```

Jalankan notebook **01 → 05 berurutan dari folder repo ini**. Notebook 01 memakai hasil scraping di
`scraped/` (`RUN_SCRAPING = False`); ubah menjadi `True` atau jalankan `python Group4_Scraping.py index`
untuk mengulang scraping. Model terlatih (IndoBERT ±500 MB, BiLSTM, BERTopic) disimpan ke folder `models/`
saat notebook dijalankan dan tidak disertakan di repositori karena ukurannya.
Pelatihan diuji pada GPU RTX 4070 Laptop (8 GB).

## Video penjelasan

`<<link video>>`

## Catatan data

Artikel dikumpulkan dari halaman publik detik.com, cnnindonesia.com, dan liputan6.com sesuai `robots.txt`
masing-masing situs (halaman yang dilarang, seperti `/search` Liputan6, tidak diakses), untuk keperluan
akademik. Antaranews tidak dipakai karena setiap artikelnya melarang crawling/pengindeksan otomatis untuk AI.
Hak cipta isi artikel tetap milik penerbit.

Semua CSV disimpan dalam UTF-8 dengan BOM sehingga dapat dibuka langsung di Excel. Kolom `url` berisi
tautan sumber setiap artikel. `raw_dataset.csv` masih berisi semua hasil scraping (termasuk artikel yang
tidak relevan dengan AI dan beberapa artikel yang sangat panjang); dataset yang dipakai untuk analisis
adalah `dataset_clean.csv` dan turunannya.
