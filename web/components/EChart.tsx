"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

/** Envoltura mínima de ECharts: actualiza la gráfica en sitio cuando cambian las opciones. */
export function EChart({ option, height = 280, onClick, replaceSeries }: {
  option: echarts.EChartsOption;
  height?: number;
  /** Quita las series que ya no vienen en las opciones (cuando un filtro cambia cuántas hay). */
  replaceSeries?: boolean;
  onClick?: (params: { dataIndex: number; seriesIndex?: number }) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const click = useRef(onClick);
  click.current = onClick;

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    chart.current.on("click", (p) => click.current?.(p as { dataIndex: number; seriesIndex?: number }));
    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(ref.current);
    return () => {
      resize.disconnect();
      chart.current?.dispose();
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option, { notMerge: false, lazyUpdate: true, replaceMerge: replaceSeries ? ["series"] : undefined });
  }, [option, replaceSeries]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
