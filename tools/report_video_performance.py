"""Summarize measured artifacts; never synthesize timing values or rewrite source footage."""
import argparse
from pathlib import Path
import json
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from software.vision.video_benchmark import compare_quality
from software.vision.project_storage import atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('build/vision_v04'))
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    gui=Path((a.root/'latest_gui.txt').read_text(encoding='utf-8'))
    evidence=json.loads((gui/'gui_evidence.json').read_text(encoding='utf-8'))
    inputs=[('1080p',a.root/'final_1080p/report'),('1440p',a.root/'final_1440p/report'),
        ('4K',a.root/'final_2160p/report'),('DISCOVER_1080p',a.root/'final_discover'),('GUI_1080p',Path(evidence['report']))]
    reports=[]
    lines=['# RGB Vision v0.4-perf — фактические измерения','',
        'Пользователь подтвердил: реального видео пока нет. Ниже только синтетические MP4, не съёмка телефона.',
        '120 кадров / 4 секунды / 30 FPS; reference grid 1200×700 при всех трёх размерах входного видео.',
        'Это меньше реальной карты GS75 4000×2256; цифры нельзя переносить на неё без нового видеозамера.',
        'Прогрев 3 кадра отдельным проходом, затем новое последовательное декодирование всех кадров с нуля.',
        'Исходный baseline A повторно регистрирует OFF; A_CACHED — контроль с кэшем, B — кэш без диагностических копий.',
        'C — уменьшенный ArUco с full-resolution refinement/fallback, coarse-фон и локальные ROI.', '']
    for label,path in inputs:
        report=json.loads((path/'benchmark.json').read_text(encoding='utf-8'))
        quality=compare_quality(report['runs'])
        truth_path=Path(report['source']).parent/'fixture.json'
        truth={r['frame']:r['expected'] for r in json.loads(truth_path.read_text(encoding='utf-8'))['frames']}
        for run in report['runs']:
            errors=[]
            for row in run['frames']:
                expected=truth[row['frame_index']]
                active=[r['color'] for r in row['records'] if r['status'] in ('ON','CANDIDATE')]
                valid=(row['registration']=='FAILED') if expected=='INVALID' else (not active if expected=='OFF' else active==[expected])
                if not valid:errors.append(row['frame_index'])
            run['synthetic_ground_truth_error_frames']=errors
            if errors:raise ValueError(f"Ground truth errors in {label}/{run['variant']}: {errors}")
        compact={k:v for k,v in report.items() if k!='runs'}
        compact.update(label=label,quality=quality,runs=[{k:v for k,v in r.items() if k!='frames'} for r in report['runs']])
        reports.append(compact)
        shutil.copy2(path/'frames.csv',a.output/(label+'_frames.csv'))
        shutil.copy2(path/'frame_times.png',a.output/(label+'_frame_times.png'))
        lines += [f'## {label}','',f"Размер входа: {report['runs'][0]['video']['width']}×{report['runs'][0]['video']['height']}; режим {report['mode']}.",
            '', '| Вариант | Mean ms | P50 | P95 | P99 | Max | FPS | RSS MiB | Quality |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---|']
        for r in report['runs']:
            t=r['end_to_end'];values=' | '.join(f'{t[k]:.3f}' for k in ('mean_ms','p50_ms','p95_ms','p99_ms','max_ms','fps'))
            lines.append(f"| {r['variant']} | {values} | {(r['peak_observed_rss_bytes'] or 0)/2**20:.1f} | {quality[r['variant']]['verdict']} |")
        lines += ['',f'![Время каждого кадра]({label}_frame_times.png)','',
            f"OFF: {report['off']['retained_frames']} совмещённых наблюдения; достоверная маска {report['off']['valid_fraction']:.3%}.",
            f"Отдельные расходы вне кадров: {report['separate_costs_ms']}. OFF setup: {report['off_setup_ms']:.1f} ms."]
        if label=='1080p':
            lines += ['', '### Стадии 1080p (exclusive)','']
            for r in report['runs']:
                lines += [f"#### {r['variant']}",'','| Стадия | Mean ms | P50 | P95 | P99 | Max |','|---|---:|---:|---:|---:|---:|']
                for name,s in r['stages'].items():
                    lines.append('| '+name+' | '+' | '.join(f'{s[k]:.4f}' for k in ('mean_ms','p50_ms','p95_ms','p99_ms','max_ms'))+' |')
                lines += ['',f"CPU: {r['cpu_machine_percent']:.2f}% всего ПК; decode FPS={r['decode']['fps']:.2f}; processing FPS={r['processing']['fps']:.2f}; wall FPS={r['wall_fps']:.2f}."]
    summary=dict(reports=reports,gui_evidence=evidence,machine=reports[0]['machine'],
        real_video_available=False,synthetic=True,reference_grid=[1200,700],
        real_rgb_regression='B_CACHED_FULL and C_HYBRID: LED49 RED/GREEN/BLUE; full-resolution fallback needed on BLUE')
    atomic_json(a.output/'summary.json',summary)
    lines += ['', '## Вывод', '',
        'На всех синтетических прогонах: 118 REGISTERED, 2 намеренно недостоверных кадра; пропусков 0, RGB ground truth без ошибок.',
        'Для C: потерь ID относительно B нет, различия центров <0,025 reference px и локальной геометрии <0,007 px.',
        'Временные события GREEN разорваны на две части при потере ArUco; через недостоверные кадры свечение не продолжается.',
        'KNOWN_LEDS C проходит короткий бюджет 30 FPS в 1080p/1440p. На 4K mean >25 ms, worst >100 ms, рекомендательный запас не выполнен.',
        'DISCOVER C: ~58 ms mean, ~65 ms P95 — 30 FPS не достигается даже на этом 1080p fixture.',
        'Без длинного реального видео и реальной карты нельзя утверждать устойчивые 30 FPS; потоковая очередь проверена только расчётной моделью.',
        'Рекомендация: C для известных LED, полный поиск при недостоверной ROI; B как контроль качества и для сложного DISCOVER.',
        'Автоматический OFF: медиана по надёжным наблюдениям, маска частоты наблюдений; не копия первого кадра.',
        'Обновление фона требует гарантированного OFF и запрещено при последнем подтверждённом свете.',
        'RSS — максимум наблюдений процесса каждые 10 ms, включает GUI/модели, не точный пик аллокатора и не изолированный subprocess peak.',
        'FRAME_TOTAL включает decode/events; стадии exclusive, нераспределённая служебная работа остаётся в FRAME_TOTAL.',
        'Матрицы камеры для benchmark пока не поддержаны: camera_model должен быть null; старый фотоанализ сохранён.',
        '', '![Гибрид и бюджет 30 FPS](hybrid_times.png)', '![Средняя/P95 по архитектурам](architecture_costs.png)']
    (a.output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig=Figure(figsize=(11,4));FigureCanvasAgg(fig);ax=fig.add_subplot()
    for label,path in inputs[:3]:
        full=json.loads((path/'benchmark.json').read_text(encoding='utf-8'))
        r=next(r for r in full['runs'] if r['variant']=='C_HYBRID')
        ax.plot([v['frame_index'] for v in r['frames']],[v['FRAME_TOTAL'] for v in r['frames']],label=label)
    ax.axhline(1000/30,linestyle='--',color='r',label='33.3 ms');ax.set(xlabel='Decoded frame',ylabel='Frame total ms',title='C_HYBRID / KNOWN_LEDS');ax.legend();fig.tight_layout();fig.savefig(a.output/'hybrid_times.png',dpi=130)
    fig=Figure(figsize=(11,4));FigureCanvasAgg(fig);ax=fig.add_subplot()
    for i,report in enumerate(reports[:3]):
        xs=[j+i*.24 for j in range(4)]
        means=[r['end_to_end']['mean_ms'] for r in report['runs']];p95=[r['end_to_end']['p95_ms'] for r in report['runs']]
        ax.bar(xs,means,width=.23,label=report['label']);ax.scatter(xs,p95,marker='_',color='k')
    ax.set_xticks([j+.24 for j in range(4)],['A baseline','A cached','B cached full','C hybrid'])
    ax.set(ylabel='ms (bar mean, black mark P95)',title='Offline decode + frame processing');ax.legend();fig.tight_layout();fig.savefig(a.output/'architecture_costs.png',dpi=130)
    print(a.output/'report.md')


if __name__=='__main__':main()
