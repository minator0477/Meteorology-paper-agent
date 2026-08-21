# 研究上の興味プロファイル（embedding による採点基準）

このファイルは論文の「面白さ」を採点するための基準です。自由に育ててください。

`## <テーマ名>` 見出し以下の本文は、そのままテーマの代表ベクトルとして埋め込まれ、
論文（title + abstract）とのコサイン類似度が採点スコアの元になります
（`scripts/score.py` 参照）。見出し名は次の5つで固定です:

  tropical / midlatitude / seam / regional / method

（`other` は「どのテーマにも強く一致しなかった」場合に自動的に割り当てられるタグなので、
ここに見出しを書く必要はありません。）

見出しの本文は具体的なキーワード・機構名・略語を並べるほど埋め込みの精度が上がります。
プレーンな日本語の説明文だけでなく、英語の専門用語・略語もそのまま含めてください
（論文側の title/abstract は英語のため）。

## 立ち位置（参考・埋め込みには使われません）
- 学生時代は **中緯度力学（ストームトラック）** が専門。ここは深く読める。
- 最近は **熱帯（MJO・ENSO・モンスーン）** にシフト中。
- 一番惹かれるのは両者の **縫い目 = 熱帯–中緯度相互作用（テレコネクション）**。
  ここに刺さる論文は高評価。

## tropical
Tropical meteorology and climate variability. MJO (Madden-Julian Oscillation),
BSISO, intraseasonal oscillation, ENSO diversity (Central Pacific / Eastern
Pacific, El Nino Modoki), IOD (Indian Ocean Dipole), Australian monsoon, Asian
summer monsoon, tropical convection, tropical cyclogenesis, Walker circulation.
熱帯気象・熱帯の季節内〜経年変動。MJO、BSISO、ENSOダイバーシティ（CP/EP、Modoki）、
IOD、豪州モンスーン、アジアモンスーン。

## midlatitude
Midlatitude dynamics. Storm track, extratropical cyclone, explosive cyclogenesis
(bomb cyclone), baroclinic instability, eddy-driven jet, jet stream, downstream
development, Rossby wave packet propagation, wave activity flux (Takaya-Nakamura),
atmospheric blocking.
中緯度力学。ストームトラック、爆弾低気圧、傾圧不安定、eddy-driven jet、下流発達、
波活動度フラックス（Takaya-Nakamura）、ブロッキング、Rossby波束伝播。

## seam
Tropical-extratropical interaction and teleconnection, the "seam" between
tropics and midlatitudes. Teleconnection patterns: PJ pattern (Pacific-Japan),
Silk Road pattern / CGT (circumglobal teleconnection), PNA (Pacific-North
American), NAO/AO (North Atlantic/Arctic Oscillation), WP (West Pacific), EU
(Eurasian) pattern. Decadal-to-multidecadal modes with tropical roots and
extratropical impact: PDO/IPO, AMO, pattern effect, internal variability vs
forced response.
熱帯–中緯度相互作用・テレコネクション。PJパターン、シルクロード/CGT、PNA、NAO/AO、
WP、EUパターン。PDO/IPO、AMOなど熱帯に起源を持ち中緯度に影響する経年〜十年変動、
pattern effect、内部変動 vs 強制応答。

## regional
East Asian and Japanese regional weather and climate extremes. Heat wave,
linear precipitation band (senjo-kousuiotai), Baiu-Meiyu front, Meiyu-Baiu
rainband, extreme precipitation over East Asia and Japan.
東アジア・日本域の極端現象。熱波、線状降水帯、梅雨前線、Baiu-Meiyu、東アジア・
日本の大雨。

## method
Reanalysis datasets and large-ensemble methodology for detection/attribution.
JRA-3Q, ERA5 reanalysis, d4PDF large ensemble, event attribution, climate model
large ensembles, statistical downscaling.
データ・手法。JRA-3Q、ERA5、d4PDF/大規模アンサンブル、イベントアトリビューション。

## 加点/減点の目安（参考・埋め込みには使われません）
- +: 上記テーマ、とくに熱帯と中緯度をまたぐ機構解明もの、非線形/多様性/レジーム依存
- +: 日本・東アジア域を扱う、または手法が上記データを使う
- -: 純粋な化学輸送・エアロゾル単体、境界層のみ、観測機器工学など興味外
- -: レビューでも新規性の薄い教科書的なもの（ただし縫い目の総説は例外的に加点）
