"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

/** Envoltura mínima de ECharts: actualiza la gráfica en sitio cuando cambian las opciones. */
export function EChart({ option, height = 280 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(ref.current);
    return () => {
      resize.disconnect();
      chart.current?.dispose();
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: false, lazyUpdate: true });
  }, [option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
