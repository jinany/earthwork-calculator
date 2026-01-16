import streamlit as st
import fitz  # PyMuPDF
from streamlit_drawable_canvas import st_canvas
from PIL import Image
from shapely.geometry import LineString, Polygon
from shapely.ops import split
import numpy as np

# =========================
# 初期化
# =========================
if "mode" not in st.session_state:
    st.session_state.mode = None
if "ground_points" not in st.session_state:
    st.session_state.ground_points = []
if "plan_points" not in st.session_state:
    st.session_state.plan_points = []
if "last_object_count" not in st.session_state:
    st.session_state.last_object_count = 0

st.set_page_config(layout="wide")
st.title("横断図 数量拾いAI（Day2 プロトタイプ）")

# =========================
# 操作ボタン
# =========================
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("地山線入力"):
        st.session_state.mode = "ground"
with col2:
    if st.button("計画線入力"):
        st.session_state.mode = "plan"
with col3:
    if st.button("全消し"):
        st.session_state.ground_points = []
        st.session_state.plan_points = []
        st.session_state.mode = None
        st.session_state.last_object_count = 0
        st.rerun()

# モード表示
mode_text = "未選択" if st.session_state.mode is None else st.session_state.mode
st.write(f"現在の入力モード：**{mode_text}**")

# =========================
# PDFアップロード
# =========================
uploaded_file = st.file_uploader("横断図PDFをアップロード（1枚）", type=["pdf"])

if uploaded_file is not None:
    # =========================
    # PDF読み込み
    # =========================
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    # =========================
    # Canvas表示
    # =========================
    # モードに応じて色を変更
    stroke_color = "#FF0000" if st.session_state.mode == "ground" else "#0000FF"
    
    canvas_result = st_canvas(
        fill_color="rgba(255, 0, 0, 0.3)",
        stroke_width=3,
        stroke_color=stroke_color,
        background_image=img,
        update_streamlit=True,
        height=img.height,
        width=img.width,
        drawing_mode="point",
        point_display_radius=5,
        key="canvas",
    )
    
    # =========================
    # クリック点取得（重複防止）
    # =========================
    if canvas_result.json_data is not None:
        objects = canvas_result.json_data.get("objects", [])
        current_count = len(objects)
        
        # 新しい点が追加された場合のみ処理
        if current_count > st.session_state.last_object_count:
            last_obj = objects[-1]
            x = last_obj["left"]
            y = last_obj["top"]
            
            if st.session_state.mode == "ground":
                st.session_state.ground_points.append((x, y))
            elif st.session_state.mode == "plan":
                st.session_state.plan_points.append((x, y))
            else:
                st.warning("先にモード（地山線 or 計画線）を選択してください")
            
            st.session_state.last_object_count = current_count

# =========================
# 状態表示（デバッグ兼）
# =========================
st.subheader("取得点情報")
colA, colB = st.columns(2)
with colA:
    st.write("**地山線 点群** 🔴")
    if st.session_state.ground_points:
        for i, (x, y) in enumerate(st.session_state.ground_points):
            st.text(f"点{i+1}: ({x:.1f}, {y:.1f})")
    st.write(f"点数：{len(st.session_state.ground_points)}")
    
with colB:
    st.write("**計画線 点群** 🔵")
    if st.session_state.plan_points:
        for i, (x, y) in enumerate(st.session_state.plan_points):
            st.text(f"点{i+1}: ({x:.1f}, {y:.1f})")
    st.write(f"点数：{len(st.session_state.plan_points)}")

st.info("💡 使い方: モードを選択 → PDF上をクリックして点を追加")
st.warning("⚠️ Day2仕様：点削除・ドラッグ・縮尺換算は未実装")

# =========================
# 土量計算セクション
# =========================
st.subheader("土量計算")

# 縮尺入力
scale = st.number_input("縮尺（1:n）", min_value=1, value=100, step=10, 
                        help="例: 1:100の場合は100を入力")

if st.button("土量を計算", type="primary"):
    if len(st.session_state.ground_points) < 2:
        st.error("地山線の点が2点以上必要です")
    elif len(st.session_state.plan_points) < 2:
        st.error("計画線の点が2点以上必要です")
    else:
        try:
            # 点を線に変換
            ground_line = LineString(st.session_state.ground_points)
            plan_line = LineString(st.session_state.plan_points)
            
            # 左右端のX座標を取得
            all_x = [p[0] for p in st.session_state.ground_points + st.session_state.plan_points]
            x_min, x_max = min(all_x), max(all_x)
            
            # 閉じたポリゴンを作成（地山線→計画線を反転→戻る）
            ground_coords = list(ground_line.coords)
            plan_coords = list(plan_line.coords)
            
            # ポリゴンを作成（時計回りまたは反時計回り）
            polygon_coords = ground_coords + plan_coords[::-1]
            polygon = Polygon(polygon_coords)
            
            # 面積計算（ピクセル単位）
            area_pixel = abs(polygon.area)
            
            # 実寸法に換算（scale^2で面積換算）
            area_real = area_pixel * (scale ** 2)
            
            # 結果表示
            col_result1, col_result2 = st.columns(2)
            with col_result1:
                st.metric("断面積（ピクセル）", f"{area_pixel:.2f} px²")
            with col_result2:
                st.metric("断面積（実寸法）", f"{area_real:.2f} 単位²")
            
            # 切土・盛土判定（簡易版：中央付近で比較）
            mid_idx = len(st.session_state.ground_points) // 2
            if mid_idx < len(st.session_state.ground_points) and mid_idx < len(st.session_state.plan_points):
                ground_y = st.session_state.ground_points[mid_idx][1]
                plan_y = st.session_state.plan_points[mid_idx][1]
                
                # Y座標は上が小さいので逆転
                if ground_y > plan_y:
                    earth_type = "切土"
                    st.success(f"✂️ 判定: **{earth_type}**")
                else:
                    earth_type = "盛土"
                    st.info(f"🏗️ 判定: **{earth_type}**")
            
            st.success("✅ 計算完了！")
            
        except Exception as e:
            st.error(f"計算エラー: {e}")
            st.info("点の順序を確認してください（左から右へ順番にクリック）")
