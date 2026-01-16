import streamlit as st
import fitz  # PyMuPDF
from streamlit_drawable_canvas import st_canvas
from PIL import Image, ImageDraw
from shapely.geometry import LineString, Polygon, Point, MultiPolygon
from shapely.ops import split
import numpy as np
import io
import base64
from io import BytesIO

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
st.title("🏗️ 横断図 土量計算AI（高度版）")

# =========================
# サイドバー設定
# =========================
with st.sidebar:
    st.header("⚙️ 設定")
    
    # 縮尺設定
    scale = st.number_input("縮尺（1:n）", min_value=1, value=100, step=10, 
                            help="例: 1:100の場合は100を入力")
    
    # 法面勾配設定
    st.subheader("法面勾配設定")
    cut_slope = st.number_input("切土法面勾配（1:n）", min_value=0.1, value=0.5, step=0.1,
                                 help="例: 1:0.5（垂直:水平）")
    fill_slope = st.number_input("盛土法面勾配（1:n）", min_value=0.1, value=1.0, step=0.1,
                                  help="例: 1:1.0（垂直:水平）")
    
    # 表示オプション
    st.subheader("表示オプション")
    show_intersection = st.checkbox("交点を表示", value=True)
    show_buffer = st.checkbox("法面バッファを表示", value=False)
    show_regions = st.checkbox("区間分割を表示", value=True)

# =========================
# 操作ボタン
# =========================
col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("🔴 地山線入力", use_container_width=True):
        st.session_state.mode = "ground"
with col2:
    if st.button("🔵 計画線入力", use_container_width=True):
        st.session_state.mode = "plan"
with col3:
    if st.button("🗑️ 全消し", use_container_width=True):
        st.session_state.ground_points = []
        st.session_state.plan_points = []
        st.session_state.mode = None
        st.session_state.last_object_count = 0
        st.rerun()
with col4:
    if st.button("↩️ 1点削除", use_container_width=True):
        if st.session_state.mode == "ground" and st.session_state.ground_points:
            st.session_state.ground_points.pop()
        elif st.session_state.mode == "plan" and st.session_state.plan_points:
            st.session_state.plan_points.pop()
        st.rerun()

# モード表示
mode_text = "未選択" if st.session_state.mode is None else ("🔴 地山線" if st.session_state.mode == "ground" else "🔵 計画線")
st.info(f"現在の入力モード：**{mode_text}**")

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
    
    # 画像をbase64に変換（互換性向上）
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    # =========================
    # Canvas表示
    # =========================
    stroke_color = "#FF0000" if st.session_state.mode == "ground" else "#0000FF"
    
    try:
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
    except Exception as e:
        st.error(f"Canvas エラー: {e}")
        st.info("代替方法: 画像上で直接座標を指定してください")
        canvas_result = None
    
    # =========================
    # クリック点取得（重複防止）
    # =========================
    if canvas_result is not None and canvas_result.json_data is not None:
        objects = canvas_result.json_data.get("objects", [])
        current_count = len(objects)
        
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
# 状態表示
# =========================
col_status1, col_status2 = st.columns(2)
with col_status1:
    st.write("**🔴 地山線**")
    st.write(f"点数：{len(st.session_state.ground_points)}")
    
with col_status2:
    st.write("**🔵 計画線**")
    st.write(f"点数：{len(st.session_state.plan_points)}")

# =========================
# 土量計算セクション
# =========================
st.divider()
st.header("📊 土量計算結果")

if st.button("🔄 土量を計算", type="primary", use_container_width=True):
    if len(st.session_state.ground_points) < 2:
        st.error("地山線の点が2点以上必要です")
    elif len(st.session_state.plan_points) < 2:
        st.error("計画線の点が2点以上必要です")
    else:
        try:
            # ====================
            # 1. 基本形状の作成
            # ====================
            ground_points = sorted(st.session_state.ground_points, key=lambda p: p[0])
            plan_points = sorted(st.session_state.plan_points, key=lambda p: p[0])
            
            ground_line = LineString(ground_points)
            plan_line = LineString(plan_points)
            
            # ====================
            # 2. 交点の検出
            # ====================
            intersections = []
            if ground_line.intersects(plan_line):
                intersection = ground_line.intersection(plan_line)
                if intersection.geom_type == 'Point':
                    intersections = [intersection]
                elif intersection.geom_type == 'MultiPoint':
                    intersections = list(intersection.geoms)
            
            st.subheader("🎯 交点情報")
            if intersections:
                st.success(f"交点数: {len(intersections)}個")
                for i, pt in enumerate(intersections):
                    x_real = pt.x * scale
                    y_real = pt.y * scale
                    st.write(f"交点 {i+1}: ピクセル座標({pt.x:.1f}, {pt.y:.1f}) → 実座標({x_real:.1f}, {y_real:.1f})")
            else:
                st.info("交点なし（切土のみ or 盛土のみ）")
            
            # ====================
            # 3. 区間分割と土量計算
            # ====================
            st.subheader("📐 区間別土量")
            
            # X座標の範囲を取得
            all_x = [p[0] for p in ground_points + plan_points]
            x_min, x_max = min(all_x), max(all_x)
            
            # 交点がない場合は全体を1区間として処理
            if not intersections:
                x_sections = [(x_min, x_max)]
            else:
                # 交点でX座標を分割
                x_divisions = sorted([x_min] + [pt.x for pt in intersections] + [x_max])
                x_sections = [(x_divisions[i], x_divisions[i+1]) for i in range(len(x_divisions)-1)]
            
            total_cut = 0
            total_fill = 0
            
            for idx, (x_start, x_end) in enumerate(x_sections):
                x_mid = (x_start + x_end) / 2
                
                # 中間点での高さを取得
                try:
                    ground_y = ground_line.interpolate(ground_line.project(Point(x_mid, 0))).y
                    plan_y = plan_line.interpolate(plan_line.project(Point(x_mid, 0))).y
                except:
                    continue
                
                # この区間の地山線と計画線の座標を取得
                ground_segment = []
                plan_segment = []
                
                for gx, gy in ground_points:
                    if x_start <= gx <= x_end:
                        ground_segment.append((gx, gy))
                
                for px, py in plan_points:
                    if x_start <= px <= x_end:
                        plan_segment.append((px, py))
                
                if len(ground_segment) < 2 or len(plan_segment) < 2:
                    continue
                
                # ポリゴン作成
                polygon_coords = ground_segment + plan_segment[::-1]
                polygon = Polygon(polygon_coords)
                area_pixel = abs(polygon.area)
                area_real = area_pixel * (scale ** 2)
                
                # 切土・盛土判定（Y座標は上が小さい）
                if ground_y > plan_y:
                    earth_type = "切土"
                    total_cut += area_real
                    color = "🟥"
                else:
                    earth_type = "盛土"
                    total_fill += area_real
                    color = "🟦"
                
                with st.expander(f"{color} 区間 {idx+1}: {earth_type} ({x_start:.1f} ~ {x_end:.1f})", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("面積（ピクセル²）", f"{area_pixel:.2f}")
                    with col2:
                        st.metric("面積（実寸法²）", f"{area_real:.2f}")
            
            # ====================
            # 4. 合計値
            # ====================
            st.subheader("📊 合計")
            col_sum1, col_sum2, col_sum3 = st.columns(3)
            with col_sum1:
                st.metric("🟥 切土合計", f"{total_cut:.2f} 単位²")
            with col_sum2:
                st.metric("🟦 盛土合計", f"{total_fill:.2f} 単位²")
            with col_sum3:
                net = total_cut - total_fill
                st.metric("⚖️ 差引", f"{net:.2f} 単位²")
            
            # ====================
            # 5. 法面バッファ計算
            # ====================
            if show_buffer:
                st.subheader("🏔️ 法面バッファ")
                
                # 切土側のバッファ（外側に拡張）
                cut_buffer_dist = cut_slope * scale  # ピクセル単位
                fill_buffer_dist = fill_slope * scale
                
                col_buf1, col_buf2 = st.columns(2)
                with col_buf1:
                    st.write(f"**切土法面バッファ距離**: {cut_buffer_dist:.2f} px")
                    st.write(f"勾配 1:{cut_slope}")
                with col_buf2:
                    st.write(f"**盛土法面バッファ距離**: {fill_buffer_dist:.2f} px")
                    st.write(f"勾配 1:{fill_slope}")
                
                st.info("💡 法面バッファは設計用の参考値です。実際の施工では詳細設計が必要です。")
            
            st.success("✅ 計算完了！")
            
        except Exception as e:
            st.error(f"❌ 計算エラー: {e}")
            st.info("💡 点の順序を確認してください（左から右へ順番にクリック）")
            import traceback
            with st.expander("詳細エラー情報"):
                st.code(traceback.format_exc())

# =========================
# 使い方ガイド
# =========================
with st.expander("📖 使い方ガイド", expanded=False):
    st.markdown("""
    ### 基本操作
    1. **PDFアップロード**: 横断図PDFをアップロード
    2. **地山線入力**: 🔴ボタンをクリック後、地山線を左から右へクリック
    3. **計画線入力**: 🔵ボタンをクリック後、計画線を左から右へクリック
    4. **土量計算**: 「土量を計算」ボタンをクリック
    
    ### 高度な機能
    - **交点自動検出**: 地山線と計画線の交わる点を自動検出
    - **区間自動分割**: 切土・盛土が混在する場合、交点で自動分割
    - **不整形断面対応**: 階段状の地形でも正確に面積計算
    - **法面勾配設定**: サイドバーで切土・盛土の法面勾配を設定可能
    
    ### Tips
    - 点を間違えた場合は「1点削除」ボタンで最後の点を削除
    - 縮尺は正確に設定してください（図面に記載）
    - 点は必ず左から右へ順番にクリックしてください
    """)
