# -*- coding: utf-8 -*-
from __future__ import division, print_function, unicode_literals

import math
import objc
from GlyphsApp import *
from GlyphsApp.plugins import *
from AppKit import (
    NSColor,
    NSBezierPath,
    NSPoint,
    NSRect,
    NSSize,
    NSString,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
    NSTextAlignmentLeft,
    NSLineBreakByClipping,
)

try:
    from fontTools.pens.statisticsPen import StatisticsPen
except ImportError:
    StatisticsPen = None


# AppKit NSBezierPath 要素タイプ定数
NSMoveToBezierPathElement = 0
NSLineToBezierPathElement = 1
NSCurveToBezierPathElement = 2
NSClosePathBezierPathElement = 3

# 各種設定キーのプレフィックスとデフォルト値
SETTING_PREFIX = "com.rikitakahashi.ShowKuromi."
LEGACY_SETTING_PREFIX = "com.rikitakahashi.ShowVisualBalance."
DEFAULT_SETTINGS = {
    "showCenterCrosshair": True,
    "showEMCrosshair": True,
    "showDeltaVector": True,
    "showDeltaBadge": True,
    "showBBoxCenter": True,
    "showInfoHUD": True,
    "showQuadrantMetrics": True,
}


class ShowKuromi(ReporterPlugin):

    @objc.python_method
    def settings(self):
        self.menuName = Glyphs.localize({
            'en': 'Show Kuromi',
            'ja': '重心と黒み',
        })

    @objc.python_method
    def background(self, layer):
        self.drawVisualBalance(layer)

    @objc.python_method
    def foreground(self, layer):
        self.drawVisualBalanceForeground(layer)

    @objc.python_method
    def __file__(self):
        return __file__

    # ----------------------------------------------------
    # 設定値の保存・取得（Glyphs.defaults 連携）
    # ----------------------------------------------------
    @objc.python_method
    def getSetting(self, key):
        val = Glyphs.defaults[SETTING_PREFIX + key]
        if val is None:
            val = Glyphs.defaults[LEGACY_SETTING_PREFIX + key]
        if val is None:
            return DEFAULT_SETTINGS.get(key, True)
        return bool(val)

    @objc.python_method
    def setSetting(self, key, val):
        Glyphs.defaults[SETTING_PREFIX + key] = bool(val)

    @objc.python_method
    def toggleSetting(self, key):
        currentVal = self.getSetting(key)
        self.setSetting(key, not currentVal)
        Glyphs.redraw()

    # ----------------------------------------------------
    # コンテキストメニュー（右クリックで表示項目のON/OFF切り替え）
    # ----------------------------------------------------
    @objc.python_method
    def conditionalContextMenus(self):
        return self.buildContextMenus()

    def conditionalContextMenus_(self, sender=None):
        return self.buildContextMenus()

    @objc.python_method
    def buildContextMenus(self):
        menuDefinitions = [
            ("showCenterCrosshair", "Show Center Crosshair", "重心十字線を表示", self.toggleCenterCrosshair_),
            ("showEMCrosshair", "Show EM Origin Crosshair", "EM中心の十字線を表示", self.toggleEMCrosshair_),
            ("showDeltaVector", "Show Delta Vector", "偏差ベクトル線を表示", self.toggleDeltaVector_),
            ("showDeltaBadge", "Show Deviation Badge", "重心の偏差情報を表示", self.toggleDeltaBadge_),
            ("showBBoxCenter", "Show BBox Center", "字面中心を表示", self.toggleBBoxCenter_),
            ("showInfoHUD", "Show Info HUD", "情報ボックスを表示", self.toggleInfoHUD_),
            ("showQuadrantMetrics", "Show Quadrant Blackness", "四象限の黒み情報を表示", self.toggleQuadrantMetrics_),
        ]

        menus = []
        for key, enText, jaText, actionMethod in menuDefinitions:
            stateMark = "✓ " if self.getSetting(key) else "    "
            localizedTitle = stateMark + Glyphs.localize({'en': enText, 'ja': jaText})
            menus.append({
                "name": localizedTitle,
                "action": actionMethod,
            })
        return menus

    # 各メニューアクションのハンドラ（Cocoaセレクタとして機能）
    def toggleCenterCrosshair_(self, sender=None):
        self.toggleSetting("showCenterCrosshair")

    def toggleEMCrosshair_(self, sender=None):
        self.toggleSetting("showEMCrosshair")

    def toggleDeltaVector_(self, sender=None):
        self.toggleSetting("showDeltaVector")

    def toggleDeltaBadge_(self, sender=None):
        self.toggleSetting("showDeltaBadge")

    def toggleBBoxCenter_(self, sender=None):
        self.toggleSetting("showBBoxCenter")

    def toggleInfoHUD_(self, sender=None):
        self.toggleSetting("showInfoHUD")

    def toggleQuadrantMetrics_(self, sender=None):
        self.toggleSetting("showQuadrantMetrics")

    # ----------------------------------------------------
    # ベジェパス走査ヘルパー
    # ----------------------------------------------------
    @objc.python_method
    def feedBezierPathToPen(self, bezierPath, pen):
        elementCount = bezierPath.elementCount()
        if elementCount == 0:
            return

        for i in range(elementCount):
            elementType, points = bezierPath.elementAtIndex_associatedPoints_(i)
            if elementType == NSMoveToBezierPathElement:
                pen.moveTo((points[0].x, points[0].y))
            elif elementType == NSLineToBezierPathElement:
                pen.lineTo((points[0].x, points[0].y))
            elif elementType == NSCurveToBezierPathElement:
                pen.curveTo(
                    (points[0].x, points[0].y),
                    (points[1].x, points[1].y),
                    (points[2].x, points[2].y),
                )
            elif elementType == NSClosePathBezierPathElement:
                pen.closePath()

    # ----------------------------------------------------
    # 四象限（4分割）黒み計算用幾何アルゴリズム（Sutherland-Hodgman 法）
    # ----------------------------------------------------
    @objc.python_method
    def extractFlattenedContours(self, bezierPath):
        try:
            flatPath = bezierPath.bezierPathByFlatteningPath()
        except Exception:
            flatPath = bezierPath

        elementCount = flatPath.elementCount()
        if elementCount == 0:
            return []

        contours = []
        current = []

        for i in range(elementCount):
            elementType, points = flatPath.elementAtIndex_associatedPoints_(i)
            if elementType == NSMoveToBezierPathElement:
                if len(current) >= 3:
                    contours.append(current)
                current = [(points[0].x, points[0].y)]
            elif elementType == NSLineToBezierPathElement:
                pt = (points[0].x, points[0].y)
                if current and (abs(pt[0] - current[-1][0]) > 1e-4 or abs(pt[1] - current[-1][1]) > 1e-4):
                    current.append(pt)
            elif elementType == NSCurveToBezierPathElement:
                pt = (points[2].x, points[2].y)
                if current and (abs(pt[0] - current[-1][0]) > 1e-4 or abs(pt[1] - current[-1][1]) > 1e-4):
                    current.append(pt)
            elif elementType == NSClosePathBezierPathElement:
                if len(current) >= 3:
                    contours.append(current)
                current = []

        if len(current) >= 3:
            contours.append(current)

        return contours

    @objc.python_method
    def clipPolygon(self, points, is_inside, intersect):
        if not points:
            return []
        output = []
        s = points[-1]
        for p in points:
            p_in = is_inside(p)
            s_in = is_inside(s)
            if p_in:
                if s_in:
                    output.append(p)
                else:
                    output.append(intersect(s, p))
                    output.append(p)
            elif s_in:
                output.append(intersect(s, p))
            s = p
        return output

    @objc.python_method
    def polygonArea(self, points):
        n = len(points)
        if n < 3:
            return 0.0
        area = 0.0
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1] - points[j][0] * points[i][1]
        return 0.5 * area

    @objc.python_method
    def intersectX(self, s, p, cx):
        dx = p[0] - s[0]
        if abs(dx) < 1e-12:
            return (cx, s[1])
        t = (cx - s[0]) / dx
        return (cx, s[1] + t * (p[1] - s[1]))

    @objc.python_method
    def intersectY(self, s, p, cy):
        dy = p[1] - s[1]
        if abs(dy) < 1e-12:
            return (s[0], cy)
        t = (cy - s[1]) / dy
        return (s[0] + t * (p[0] - s[0]), cy)

    @objc.python_method
    def computeQuadrantAreas(self, contours, cx, cy):
        # 戻り値のインデックス対応: 0: TL(左上), 1: TR(右上), 2: BL(左下), 3: BR(右下)
        raw_areas = [0.0, 0.0, 0.0, 0.0]
        for c in contours:
            if len(c) < 3:
                continue
            left = self.clipPolygon(c, lambda p: p[0] <= cx, lambda s, p: self.intersectX(s, p, cx))
            right = self.clipPolygon(c, lambda p: p[0] >= cx, lambda s, p: self.intersectX(s, p, cx))
            if left:
                tl = self.clipPolygon(left, lambda p: p[1] >= cy, lambda s, p: self.intersectY(s, p, cy))
                bl = self.clipPolygon(left, lambda p: p[1] <= cy, lambda s, p: self.intersectY(s, p, cy))
                raw_areas[0] += self.polygonArea(tl)
                raw_areas[2] += self.polygonArea(bl)
            if right:
                tr = self.clipPolygon(right, lambda p: p[1] >= cy, lambda s, p: self.intersectY(s, p, cy))
                br = self.clipPolygon(right, lambda p: p[1] <= cy, lambda s, p: self.intersectY(s, p, cy))
                raw_areas[1] += self.polygonArea(tr)
                raw_areas[3] += self.polygonArea(br)
        return raw_areas

    @objc.python_method
    def calculateQuadrantMetrics(self, completePath, emCenterX, emCenterY, blackArea, emArea):
        try:
            contours = self.extractFlattenedContours(completePath)
            if not contours:
                return (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)

            raw_areas = self.computeQuadrantAreas(contours, emCenterX, emCenterY)
            sum_raw = sum(abs(a) for a in raw_areas)

            if sum_raw > 1e-4:
                area_TL = blackArea * (abs(raw_areas[0]) / sum_raw)
                area_TR = blackArea * (abs(raw_areas[1]) / sum_raw)
                area_BL = blackArea * (abs(raw_areas[2]) / sum_raw)
                area_BR = blackArea * (abs(raw_areas[3]) / sum_raw)
            else:
                area_TL = area_TR = area_BL = area_BR = 0.0

            # 象限EM面積に対する充填率（Area / (emArea / 4)）
            quadEmArea = (emArea / 4.0) if emArea > 0 else 1.0
            fill_TL = (area_TL / quadEmArea) * 100.0
            fill_TR = (area_TR / quadEmArea) * 100.0
            fill_BL = (area_BL / quadEmArea) * 100.0
            fill_BR = (area_BR / quadEmArea) * 100.0

            # 全体黒みに対する構成比（Area / blackArea）
            totalBlack = blackArea if blackArea > 0 else 1.0
            share_TL = (area_TL / totalBlack) * 100.0
            share_TR = (area_TR / totalBlack) * 100.0
            share_BL = (area_BL / totalBlack) * 100.0
            share_BR = (area_BR / totalBlack) * 100.0

            return (
                (area_TL, area_TR, area_BL, area_BR),
                (fill_TL, fill_TR, fill_BL, fill_BR),
                (share_TL, share_TR, share_BL, share_BR),
            )
        except Exception as e:
            print("ShowKuromi calculateQuadrantMetrics Error: {}".format(e))
            return (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)

    # ----------------------------------------------------
    # メイン描画処理（レイヤー背景：ガイドライン・重心・各中心マーカー）
    # ----------------------------------------------------
    @objc.python_method
    def drawVisualBalance(self, layer):
        try:
            if not layer:
                return

            font = layer.font()
            if not font or StatisticsPen is None:
                return

            completePath = layer.completeBezierPath
            if not completePath or completePath.elementCount() == 0:
                return

            # 1. StatisticsPen による面積および重心（Center of Mass）の計算
            pen = StatisticsPen()
            self.feedBezierPathToPen(completePath, pen)

            area = pen.area
            if area is None or abs(area) < 1e-4:
                return

            meanX = pen.meanX
            meanY = pen.meanY
            if meanX is None or meanY is None:
                return

            blackArea = abs(area)

            # 2. 仮想ボディ（EM Square）メトリクスの取得と中心点の算出
            upm = float(font.upm) if font.upm else 1000.0
            master = layer.master
            descender = float(master.descender) if master and master.descender is not None else 0.0
            glyphWidth = float(layer.width) if layer.width is not None else upm

            emArea = upm * glyphWidth
            emCenterX = glyphWidth / 2.0
            emCenterY = descender + (upm / 2.0)

            fillRate = (blackArea / emArea) * 100.0 if emArea > 0 else 0.0
            deltaX = meanX - emCenterX
            deltaY = meanY - emCenterY

            # 3. 4象限（四分割）黒み計算
            quadrantAreas = None
            quadrantFills = None
            quadrantShares = None
            if self.getSetting("showQuadrantMetrics"):
                quadrantAreas, quadrantFills, quadrantShares = self.calculateQuadrantMetrics(
                    completePath=completePath,
                    emCenterX=emCenterX,
                    emCenterY=emCenterY,
                    blackArea=blackArea,
                    emArea=emArea,
                )

            # 4. 字面バウンディングボックス（BBox）中心の算出
            bounds = layer.bounds
            bboxCenterX = bounds.origin.x + (bounds.size.width / 2.0)
            bboxCenterY = bounds.origin.y + (bounds.size.height / 2.0)

            # 5. ズーム倍率の取得（画面上の実ピクセルサイズを維持するため）
            scale = self.getScale()
            if scale <= 0:
                scale = 1.0

            # ----------------------------------------------------
            # 描画レイヤー A: 仮想ボディ（Em Square）の輪郭と中心マーカー
            # ----------------------------------------------------
            emRectPath = NSBezierPath.bezierPathWithRect_(
                NSRect(NSPoint(0, descender), NSSize(glyphWidth, upm))
            )
            emRectPath.setLineWidth_(1.0 / scale)
            try:
                emRectPath.setLineDash_count_phase_([4.0 / scale, 4.0 / scale], 2, 0.0)
            except Exception:
                pass
            NSColor.colorWithCalibratedWhite_alpha_(0.5, 0.22).set()
            emRectPath.stroke()

            # EM中心のダイヤマーカー
            emCenterMarkerRadius = 4.0 / scale
            emDiamond = NSBezierPath.bezierPath()
            emDiamond.moveToPoint_(NSPoint(emCenterX, emCenterY + emCenterMarkerRadius))
            emDiamond.lineToPoint_(NSPoint(emCenterX + emCenterMarkerRadius, emCenterY))
            emDiamond.lineToPoint_(NSPoint(emCenterX, emCenterY - emCenterMarkerRadius))
            emDiamond.lineToPoint_(NSPoint(emCenterX - emCenterMarkerRadius, emCenterY))
            emDiamond.closePath()
            emDiamond.setLineWidth_(1.0 / scale)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.60, 0.95, 0.75).set()
            emDiamond.stroke()

            # ----------------------------------------------------
            # 描画レイヤー B: 仮想ボディ中心（EM Center）を通る直交十字線
            # ----------------------------------------------------
            if self.getSetting("showEMCrosshair"):
                infSpan = 50000.0
                emCrossPath = NSBezierPath.bezierPath()
                # 水平線
                emCrossPath.moveToPoint_(NSPoint(-infSpan, emCenterY))
                emCrossPath.lineToPoint_(NSPoint(infSpan, emCenterY))
                # 垂直線
                emCrossPath.moveToPoint_(NSPoint(emCenterX, -infSpan))
                emCrossPath.lineToPoint_(NSPoint(emCenterX, infSpan))

                emCrossPath.setLineWidth_(0.8 / scale)
                try:
                    emCrossPath.setLineDash_count_phase_([5.0 / scale, 4.0 / scale], 2, 0.0)
                except Exception:
                    pass
                # 重心の赤線と明確に区別できる薄いシアン・ブルー
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.65, 1.0, 0.38).set()
                emCrossPath.stroke()

            # ----------------------------------------------------
            # 描画レイヤー C: 重心通過ライン（重心を通る直交十字線）
            # ----------------------------------------------------
            if self.getSetting("showCenterCrosshair"):
                infSpan = 50000.0
                centerCrossPath = NSBezierPath.bezierPath()
                # 水平線
                centerCrossPath.moveToPoint_(NSPoint(-infSpan, meanY))
                centerCrossPath.lineToPoint_(NSPoint(infSpan, meanY))
                # 垂直線
                centerCrossPath.moveToPoint_(NSPoint(meanX, -infSpan))
                centerCrossPath.lineToPoint_(NSPoint(meanX, infSpan))

                centerCrossPath.setLineWidth_(0.8 / scale)
                try:
                    centerCrossPath.setLineDash_count_phase_([3.0 / scale, 3.0 / scale], 2, 0.0)
                except Exception:
                    pass
                # 薄いコーラルレッド
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.32, 0.20, 0.35).set()
                centerCrossPath.stroke()

            # ----------------------------------------------------
            # 描画レイヤー D: 字面バウンディングボックス中心（BBox Center）
            # 重心マーカーと同等の迫力・サイズ、鮮やかなアンバーオレンジで描画
            # ----------------------------------------------------
            if self.getSetting("showBBoxCenter"):
                bboxMarkerRadius = 7.2 / scale
                bboxCrossLength = 11.0 / scale
                bboxDotRadius = 1.6 / scale

                # コントラスト用下地（白フチ）
                bgBBoxOutline = NSBezierPath.bezierPath()
                bgBBoxOutline.moveToPoint_(NSPoint(bboxCenterX, bboxCenterY + bboxMarkerRadius))
                bgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX + bboxMarkerRadius, bboxCenterY))
                bgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX, bboxCenterY - bboxMarkerRadius))
                bgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX - bboxMarkerRadius, bboxCenterY))
                bgBBoxOutline.closePath()
                bgBBoxOutline.moveToPoint_(NSPoint(bboxCenterX - bboxCrossLength, bboxCenterY))
                bgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX + bboxCrossLength, bboxCenterY))
                bgBBoxOutline.moveToPoint_(NSPoint(bboxCenterX, bboxCenterY - bboxCrossLength))
                bgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX, bboxCenterY + bboxCrossLength))

                bgBBoxOutline.setLineWidth_(3.0 / scale)
                NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.85).set()
                bgBBoxOutline.stroke()

                # 前面（鮮やかなアンバーオレンジ）
                fgBBoxOutline = NSBezierPath.bezierPath()
                fgBBoxOutline.moveToPoint_(NSPoint(bboxCenterX, bboxCenterY + bboxMarkerRadius))
                fgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX + bboxMarkerRadius, bboxCenterY))
                fgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX, bboxCenterY - bboxMarkerRadius))
                fgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX - bboxMarkerRadius, bboxCenterY))
                fgBBoxOutline.closePath()
                fgBBoxOutline.moveToPoint_(NSPoint(bboxCenterX - bboxCrossLength, bboxCenterY))
                fgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX + bboxCrossLength, bboxCenterY))
                fgBBoxOutline.moveToPoint_(NSPoint(bboxCenterX, bboxCenterY - bboxCrossLength))
                fgBBoxOutline.lineToPoint_(NSPoint(bboxCenterX, bboxCenterY + bboxCrossLength))

                fgBBoxOutline.setLineWidth_(1.4 / scale)
                bboxColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.52, 0.0, 0.95)
                bboxColor.set()
                fgBBoxOutline.stroke()

                # 中心小ドット
                bboxDot = NSBezierPath.bezierPathWithOvalInRect_(
                    NSRect(
                        NSPoint(bboxCenterX - bboxDotRadius, bboxCenterY - bboxDotRadius),
                        NSSize(bboxDotRadius * 2.0, bboxDotRadius * 2.0),
                    )
                )
                bboxColor.set()
                bboxDot.fill()

            # ----------------------------------------------------
            # 描画レイヤー E: 偏差ベクトル（EM中心 → 重心マーカーへの矢印結線）
            # ----------------------------------------------------
            if self.getSetting("showDeltaVector"):
                self.drawDeltaVector(
                    emCenterX=emCenterX,
                    emCenterY=emCenterY,
                    meanX=meanX,
                    meanY=meanY,
                    deltaX=deltaX,
                    deltaY=deltaY,
                    scale=scale,
                )

            # ----------------------------------------------------
            # 描画レイヤー E-2: 重心マーカー近傍の偏差情報ブロック（差分バッジ）
            # ----------------------------------------------------
            if self.getSetting("showDeltaBadge"):
                self.drawDeltaBadge(
                    meanX=meanX,
                    meanY=meanY,
                    deltaX=deltaX,
                    deltaY=deltaY,
                    scale=scale,
                )

            # ----------------------------------------------------
            # 描画レイヤー F: 重心マーカー（視認性の高い二重円＋十字スレッド）
            # ----------------------------------------------------
            markerOuterRadius = 7.0 / scale
            crosshairLength = 11.0 / scale
            centerDotRadius = 1.6 / scale

            # コントラスト用下地（白フチ）
            bgOutlinePath = NSBezierPath.bezierPath()
            bgOutlinePath.appendBezierPath_(
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSRect(
                        NSPoint(meanX - markerOuterRadius, meanY - markerOuterRadius),
                        NSSize(markerOuterRadius * 2.0, markerOuterRadius * 2.0),
                    )
                )
            )
            bgOutlinePath.moveToPoint_(NSPoint(meanX - crosshairLength, meanY))
            bgOutlinePath.lineToPoint_(NSPoint(meanX + crosshairLength, meanY))
            bgOutlinePath.moveToPoint_(NSPoint(meanX, meanY - crosshairLength))
            bgOutlinePath.lineToPoint_(NSPoint(meanX, meanY + crosshairLength))

            bgOutlinePath.setLineWidth_(3.0 / scale)
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.85).set()
            bgOutlinePath.stroke()

            # 前面スレッド（鮮やかなレッド）
            fgMarkerPath = NSBezierPath.bezierPath()
            fgMarkerPath.appendBezierPath_(
                NSBezierPath.bezierPathWithOvalInRect_(
                    NSRect(
                        NSPoint(meanX - markerOuterRadius, meanY - markerOuterRadius),
                        NSSize(markerOuterRadius * 2.0, markerOuterRadius * 2.0),
                    )
                )
            )
            fgMarkerPath.moveToPoint_(NSPoint(meanX - crosshairLength, meanY))
            fgMarkerPath.lineToPoint_(NSPoint(meanX + crosshairLength, meanY))
            fgMarkerPath.moveToPoint_(NSPoint(meanX, meanY - crosshairLength))
            fgMarkerPath.lineToPoint_(NSPoint(meanX, meanY + crosshairLength))

            fgMarkerPath.setLineWidth_(1.4 / scale)
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.15, 0.15, 0.95).set()
            fgMarkerPath.stroke()

            # 中心の塗りつぶし小ドット
            centerDot = NSBezierPath.bezierPathWithOvalInRect_(
                NSRect(
                    NSPoint(meanX - centerDotRadius, meanY - centerDotRadius),
                    NSSize(centerDotRadius * 2.0, centerDotRadius * 2.0),
                )
            )
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.15, 0.15, 1.0).set()
            centerDot.fill()

            # 計算結果をキャッシュ（foreground での情報テキストHUD描画用）
            if not hasattr(self, "_metricsCache"):
                self._metricsCache = {}
            self._metricsCache[layer.layerId] = (
                blackArea, fillRate, meanX, meanY, deltaX, deltaY, descender, scale,
                quadrantAreas, quadrantFills, quadrantShares
            )

        except Exception as e:
            print("ShowKuromi Error: {}".format(e))

    # ----------------------------------------------------
    # 最上面描画処理（ビュー前面コールバック：情報テキスト HUD パネル）
    # 下のグリフと重なっても最前面に表示
    # ----------------------------------------------------
    @objc.python_method
    def drawVisualBalanceForeground(self, layer):
        try:
            if not self.getSetting("showInfoHUD"):
                return
            if not layer:
                return

            cached = getattr(self, "_metricsCache", {}).get(layer.layerId)
            if cached and len(cached) == 11:
                (blackArea, fillRate, meanX, meanY, deltaX, deltaY, descender, scale,
                 quadrantAreas, quadrantFills, quadrantShares) = cached
            else:
                font = layer.font()
                if not font or StatisticsPen is None:
                    return

                completePath = layer.completeBezierPath
                if not completePath or completePath.elementCount() == 0:
                    return

                pen = StatisticsPen()
                self.feedBezierPathToPen(completePath, pen)

                area = pen.area
                if area is None or abs(area) < 1e-4:
                    return

                meanX = pen.meanX
                meanY = pen.meanY
                if meanX is None or meanY is None:
                    return

                blackArea = abs(area)

                upm = float(font.upm) if font.upm else 1000.0
                master = layer.master
                descender = float(master.descender) if master and master.descender is not None else 0.0
                glyphWidth = float(layer.width) if layer.width is not None else upm

                emArea = upm * glyphWidth
                emCenterX = glyphWidth / 2.0
                emCenterY = descender + (upm / 2.0)

                fillRate = (blackArea / emArea) * 100.0 if emArea > 0 else 0.0
                deltaX = meanX - emCenterX
                deltaY = meanY - emCenterY

                quadrantAreas = None
                quadrantFills = None
                quadrantShares = None
                if self.getSetting("showQuadrantMetrics"):
                    quadrantAreas, quadrantFills, quadrantShares = self.calculateQuadrantMetrics(
                        completePath=completePath,
                        emCenterX=emCenterX,
                        emCenterY=emCenterY,
                        blackArea=blackArea,
                        emArea=emArea,
                    )

                scale = self.getScale()
                if scale <= 0:
                    scale = 1.0

            # ----------------------------------------------------
            # 描画レイヤー G: 情報テキスト HUD パネル（最上面描画）
            # ----------------------------------------------------
            self.drawInfoHUD(
                layer=layer,
                blackArea=blackArea,
                fillRate=fillRate,
                meanX=meanX,
                meanY=meanY,
                deltaX=deltaX,
                deltaY=deltaY,
                descender=descender,
                scale=scale,
                quadrantAreas=quadrantAreas,
                quadrantFills=quadrantFills,
                quadrantShares=quadrantShares,
            )
        except Exception as e:
            print("ShowKuromi drawVisualBalanceForeground Error: {}".format(e))

    # ----------------------------------------------------
    # 偏差ベクトル（矢印付き結線）描画
    # ----------------------------------------------------
    @objc.python_method
    def drawDeltaVector(self, emCenterX, emCenterY, meanX, meanY, deltaX, deltaY, scale):
        dist = math.hypot(deltaX, deltaY)
        vectorColor = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.50, 0.98, 0.88)

        # 1. EM中心から重心マーカーへの結線
        vectorGuide = NSBezierPath.bezierPath()
        vectorGuide.moveToPoint_(NSPoint(emCenterX, emCenterY))
        vectorGuide.lineToPoint_(NSPoint(meanX, meanY))
        vectorGuide.setLineWidth_(1.2 / scale)
        try:
            vectorGuide.setLineDash_count_phase_([4.0 / scale, 3.0 / scale], 2, 0.0)
        except Exception:
            pass
        vectorColor.set()
        vectorGuide.stroke()

        # 2. 矢頭（Arrowhead）の描画（距離が十分ある場合）
        targetOffset = 7.0 / scale  # 重心マーカーの外周手前に矢頭を配置
        if dist > (12.0 / scale):
            angle = math.atan2(deltaY, deltaX)
            arrowTipX = meanX - (targetOffset * math.cos(angle))
            arrowTipY = meanY - (targetOffset * math.sin(angle))

            arrowLength = 7.0 / scale
            arrowSpread = math.radians(26)

            leftArmX = arrowTipX - (arrowLength * math.cos(angle - arrowSpread))
            leftArmY = arrowTipY - (arrowLength * math.sin(angle - arrowSpread))
            rightArmX = arrowTipX - (arrowLength * math.cos(angle + arrowSpread))
            rightArmY = arrowTipY - (arrowLength * math.sin(angle + arrowSpread))

            arrowHead = NSBezierPath.bezierPath()
            arrowHead.moveToPoint_(NSPoint(arrowTipX, arrowTipY))
            arrowHead.lineToPoint_(NSPoint(leftArmX, leftArmY))
            arrowHead.lineToPoint_(NSPoint(rightArmX, rightArmY))
            arrowHead.closePath()

            vectorColor.set()
            arrowHead.fill()

    # ----------------------------------------------------
    # 重心マーカー近傍の偏差情報ブロック（差分バッジ）描画
    # ----------------------------------------------------
    @objc.python_method
    def drawDeltaBadge(self, meanX, meanY, deltaX, deltaY, scale):
        def formatOffset(val):
            if abs(val - round(val)) < 0.05:
                return "{:+.0f}".format(val)
            return "{:+.1f}".format(val)

        diffText = "ΔX: {}, ΔY: {}".format(formatOffset(deltaX), formatOffset(deltaY))

        fontSize = 8.5 / scale
        font = None
        if hasattr(NSFont, "monospacedDigitSystemFontOfSize_weight_"):
            font = NSFont.monospacedDigitSystemFontOfSize_weight_(fontSize, 0.0)
        if font is None:
            font = NSFont.systemFontOfSize_(fontSize)

        textAttributes = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(0.96, 0.95),
        }

        nsDiffText = NSString.stringWithString_(diffText)
        textSize = nsDiffText.sizeWithAttributes_(textAttributes)

        padX = 4.5 / scale
        padY = 2.5 / scale
        badgeWidth = textSize.width + (padX * 2.0)
        badgeHeight = textSize.height + (padY * 2.0)

        badgePosX = meanX + (10.0 / scale)
        badgePosY = meanY + (6.0 / scale)
        badgeRect = NSRect(NSPoint(badgePosX, badgePosY), NSSize(badgeWidth, badgeHeight))

        # バッジ背景（半透明ダークピル）
        badgeBg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            badgeRect, 3.0 / scale, 3.0 / scale
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.82).set()
        badgeBg.fill()

        badgeBg.setLineWidth_(0.8 / scale)
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.22).set()
        badgeBg.stroke()

        # テキスト描画
        nsDiffText.drawAtPoint_withAttributes_(
            NSPoint(badgePosX + padX, badgePosY + padY),
            textAttributes
        )

    # ----------------------------------------------------
    # 情報テキスト HUD パネル描画（和文フォント設計向け日本語表記・最上面対応）
    # ----------------------------------------------------
    @objc.python_method
    def drawInfoHUD(self, layer, blackArea, fillRate, meanX, meanY, deltaX, deltaY, descender, scale,
                    quadrantAreas=None, quadrantFills=None, quadrantShares=None):
        # 基本メトリクス
        text = (
            "黒み面積: {:,.0f} units²\n"
            "黒み比率: {:.1f}%\n"
            "重心座標: ({:.1f}, {:.1f})\n"
            "中心偏差: (X: {:+.1f}, Y: {:+.1f})"
        ).format(blackArea, fillRate, meanX, meanY, deltaX, deltaY)

        # 四象限（4分割）の黒みメトリクス（左上・右上・左下・右下）
        if self.getSetting("showQuadrantMetrics") and quadrantAreas:
            area_TL, area_TR, area_BL, area_BR = quadrantAreas
            fill_TL, fill_TR, fill_BL, fill_BR = quadrantFills
            share_TL, share_TR, share_BL, share_BR = quadrantShares

            quadText = (
                "\n象限ごとの構成比:\n"
                "  ↖ {:.1f}%   ↗ {:.1f}%\n"
                "  ↙ {:.1f}%   ↘ {:.1f}%"
            ).format(
                share_TL, share_TR,
                share_BL, share_BR,
            )
            text += quadText

        fontSize = 10.0 / scale
        padX = 8.5 / scale
        padY = 6.5 / scale
        cornerRadius = 4.0 / scale

        # 和文・英数・数値を美しく描画するシステムフォント（ヒラギノ角ゴシック / SF Pro）
        font = None
        if hasattr(NSFont, "systemFontOfSize_weight_"):
            font = NSFont.systemFontOfSize_weight_(fontSize, 0.0)
        if font is None:
            font = NSFont.systemFontOfSize_(fontSize)

        paragraphStyle = NSMutableParagraphStyle.alloc().init()
        paragraphStyle.setLineBreakMode_(NSLineBreakByClipping)
        paragraphStyle.setAlignment_(NSTextAlignmentLeft)
        paragraphStyle.setLineSpacing_(2.8 / scale)

        attributes = {
            NSFontAttributeName: font,
            NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(0.96, 0.95),
            NSParagraphStyleAttributeName: paragraphStyle,
        }

        nsText = NSString.stringWithString_(text)
        textSize = nsText.sizeWithAttributes_(attributes)

        boxWidth = textSize.width + (padX * 2.0)
        boxHeight = textSize.height + (padY * 2.0)

        posX = 0.0
        posY = descender - boxHeight - (16.0 / scale)

        boxRect = NSRect(NSPoint(posX, posY), NSSize(boxWidth, boxHeight))

        # 半透明ダーク背景（下のグリフと重なっても背後の黒みが透けすぎないよう遮蔽度を高めに設定）
        bgPath = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            boxRect, cornerRadius, cornerRadius
        )
        NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.90).set()
        bgPath.fill()

        bgPath.setLineWidth_(1.0 / scale)
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.25).set()
        bgPath.stroke()

        textOrigin = NSPoint(posX + padX, posY + padY)
        nsText.drawAtPoint_withAttributes_(textOrigin, attributes)
