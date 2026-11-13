# Dump the worst setup-timing paths for the clk_sys domain, and for every other clock whose setup or
# hold slack is negative (paths into that clock from any clock, its own included), from the
# already-compiled database, without a recompile. Run from the directory that
# holds the database (the repo root for build.sh, build/ for build_staged.py):
#   quartus_sta -t scripts/report_worst_paths.tcl <revision>
# The revision is the trailing argument; it defaults to the one below.
set rev ""
if {[llength $quartus(args)] > 0} { set rev [lindex $quartus(args) 0] }
if {$rev eq ""} {
    set qsfs [glob -nocomplain *.qsf]
    if {[llength $qsfs] != 1} { puts "give the revision: quartus_sta -t report_worst_paths.tcl <rev>"; exit 1 }
    set rev [file rootname [lindex $qsfs 0]]
}
project_open $rev
create_timing_netlist
read_sdc
update_timing_netlist

# The main core clock, as the STA names it: STA_CLOCK, which the MCP sets from the
# core's scripts/core.json sta_clock (default: the framework's emu PLL output 0, the
# same on every core built from the template).
set clk $env(STA_CLOCK)

report_timing -setup -npaths 15 -detail full_path -from_clock $clk -to_clock $clk \
    -panel_name "Worst 15 setup paths (clk_sys)" -file "output_files/worst_paths_$rev.rpt"

# Every clock that fails, not only STA_CLOCK: the worst 15 paths ending at it, setup and/or hold,
# in output_files/worst_paths_<rev>_clocks.rpt. One "CLK-SLACK" line per clock goes to the log.
set all_rpt "output_files/worst_paths_${rev}_clocks.rpt"
file delete -force $all_rpt
foreach_in_collection c [get_clocks] {
    set cn [get_clock_info -name $c]
    set res {}
    foreach kind {setup hold} {
        set worst ""
        foreach_in_collection p [get_timing_paths -$kind -to_clock $cn -npaths 1] {
            set worst [get_path_info $p -slack]
        }
        lappend res $worst
        if {$worst ne "" && $worst < 0} {
            report_timing -$kind -to_clock $cn -npaths 15 -detail full_path -append \
                -panel_name "Worst 15 $kind paths into $cn" -file $all_rpt
        }
    }
    puts "CLK-SLACK $cn setup [lindex $res 0] hold [lindex $res 1]"
}

delete_timing_netlist
# -dont_export_assignments: project_close otherwise RE-SAVES the .qsf,
# reordering it and reverting hand edits (a VERILOG_MACRO has been lost that way).
project_close -dont_export_assignments
