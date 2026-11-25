# Operating Systems Unit 2: CPU Scheduling

## Goal of CPU scheduling
CPU scheduling decides which process in the ready queue gets the CPU next. Good scheduling improves CPU utilisation and throughput and reduces waiting time, turnaround time and response time.

## First Come First Served (FCFS)
FCFS runs processes in the order they arrive. It is simple but suffers from the convoy effect, where short processes wait behind one long process, which increases the average waiting time.

## Shortest Job First (SJF)
SJF picks the process with the smallest CPU burst. Non-preemptive SJF gives the minimum average waiting time for a given set of processes, but it needs the burst time in advance and can cause starvation of long processes. The preemptive version is called Shortest Remaining Time First (SRTF).

## Round Robin (RR)
Round Robin gives every process a fixed time quantum in a circular order. It is designed for time-sharing systems. A very large quantum makes RR behave like FCFS, while a very small quantum causes too many context switches.

## Priority scheduling
Priority scheduling runs the process with the highest priority first. Low-priority processes can starve; aging solves starvation by gradually increasing the priority of processes that wait for a long time.

## Formulas to remember
Turnaround time = completion time - arrival time. Waiting time = turnaround time - burst time. Response time = time of first CPU allocation - arrival time.
