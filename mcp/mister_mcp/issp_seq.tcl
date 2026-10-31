# Run a list of ISSP steps in ONE In-System Sources and Probes session.
#
#   quartus_stp -t issp_seq.tcl <steps.txt> <out.txt>
#
# steps.txt, one per line:  read <id> | set <id> <v> | pulse <id> <v> | clear <id> | sleep <ms>
# out.txt gets: READ <id> <ms since start> <raw bits, MSB first>  and  OK <step> <ms>
# Device and instance discovery as scripts/read_issp.tcl does it.

lassign $argv steps_file out_file
set fh [open $steps_file r]; set steps [split [string trim [read $fh]] "\n"]; close $fh
set out [open $out_file w]

set hw ""
foreach h [get_hardware_names] { if {$hw eq ""} { set hw $h } }
if {$hw eq ""} { puts "NO JTAG HARDWARE FOUND"; exit 1 }
set dev ""
foreach d [get_device_names -hardware_name $hw] {
    if {[string match "*5CSE*" $d] || $dev eq ""} { set dev $d }
}
if {$dev eq ""} { puts "NO DEVICE FOUND"; exit 1 }

# Instance info has to be read before the session starts.
array set idx {}
foreach i [get_insystem_source_probe_instance_info -hardware_name $hw -device_name $dev] {
    set idx([lindex $i 3]) [lindex $i 0]
    puts $out "INSTANCE [lindex $i 3] [lindex $i 0]"
}
proc index_of {id} {
    global idx
    if {![info exists idx($id)]} { puts "NO ISSP INSTANCE $id"; exit 1 }
    return $idx($id)
}
# write_source_data takes binary unless -value_in_hex; a decimal "8" is silently rejected.
proc write_src {i v} { write_source_data -instance_index $i -value [format %X $v] -value_in_hex }

start_insystem_source_probe -device_name $dev -hardware_name $hw
set t0 [clock milliseconds]
foreach s $steps {
    set s [string trim $s]
    if {$s eq ""} continue
    lassign $s op id v
    switch -- $op {
        read  { puts $out "READ $id [expr {[clock milliseconds] - $t0}] [read_probe_data -instance_index [index_of $id]]" }
        set   { write_src [index_of $id] $v }
        pulse { set i [index_of $id]; write_src $i $v; write_src $i 0 }
        clear { set i [index_of $id]; write_src $i 1; write_src $i 0 }
        sleep { after $id }
        default { puts "bad step: $s"; end_insystem_source_probe; exit 1 }
    }
    puts $out "OK {$s} [expr {[clock milliseconds] - $t0}]"
    flush $out
}
end_insystem_source_probe
close $out
