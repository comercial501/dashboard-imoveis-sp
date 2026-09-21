package XlsxExtract;
# Minimal .xlsx reader used by build_data.pl.
# No CPAN dependencies: reads the zip entries via the system `unzip` binary
# and parses the OOXML sheet/sharedStrings XML with regexes (fast enough for
# the row/column volumes in this project; not a general-purpose XML parser).
use strict;
use warnings;
use Exporter 'import';

our @EXPORT_OK = qw(read_shared_strings read_sheet_rows col_letter_to_num read_workbook_sheets);

sub decode_xml {
    my ($s) = @_;
    return '' unless defined $s;
    $s =~ s/&lt;/</g;
    $s =~ s/&gt;/>/g;
    $s =~ s/&quot;/"/g;
    $s =~ s/&apos;/'/g;
    $s =~ s/&amp;/&/g;
    return $s;
}

sub col_letter_to_num {
    my ($col) = @_;
    my $n = 0;
    for my $ch (split //, $col) {
        $n = $n * 26 + (ord($ch) - ord('A') + 1);
    }
    return $n;
}

# Returns arrayref of shared strings (index = position in sharedStrings.xml)
sub read_shared_strings {
    my ($zip_path) = @_;
    my @shared;
    open(my $fh, '-|:encoding(UTF-8)', 'unzip', '-p', $zip_path, 'xl/sharedStrings.xml')
        or die "unzip failed for $zip_path: $!";
    local $/;
    my $content = <$fh>;
    close $fh;
    return \@shared unless defined $content;
    while ($content =~ /<si[^>]*>(.*?)<\/si>/gs) {
        my $si = $1;
        my $text = '';
        while ($si =~ /<t[^>]*>(.*?)<\/t>/gs) { $text .= $1; }
        push @shared, decode_xml($text);
    }
    return \@shared;
}

# Streams rows from a worksheet entry. Calls $callback->($row_num, \%cells)
# where %cells maps column-letter => decoded value (only non-empty cells).
sub read_sheet_rows {
    my ($zip_path, $sheet_entry, $shared, $callback) = @_;
    open(my $fh, '-|:encoding(UTF-8)', 'unzip', '-p', $zip_path, $sheet_entry)
        or die "unzip failed for $zip_path ($sheet_entry): $!";
    local $/;
    my $content = <$fh>;
    close $fh;
    return unless defined $content;

    while ($content =~ /<row[^>]*\br="(\d+)"[^>]*>(.*?)<\/row>/gs) {
        my ($rnum, $rowxml) = ($1, $2);
        my %cells;
        while ($rowxml =~ /<c\s+r="([A-Z]+)(\d+)"([^>]*?)(?:\/>|>(.*?)<\/c>)/gs) {
            my ($col, $attrs, $inner) = ($1, $3, $4);
            $inner = '' unless defined $inner;
            my $type = '';
            if ($attrs =~ /t="([^"]+)"/) { $type = $1; }
            my $val;
            if ($type eq 's') {
                if ($inner =~ /<v>(\d+)<\/v>/) { $val = $shared->[$1]; }
            } elsif ($type eq 'str') {
                if ($inner =~ /<v>(.*?)<\/v>/s) { $val = decode_xml($1); }
            } elsif ($type eq 'inlineStr') {
                if ($inner =~ /<t[^>]*>(.*?)<\/t>/s) { $val = decode_xml($1); }
            } else {
                if ($inner =~ /<v>(.*?)<\/v>/s) { $val = decode_xml($1); }
            }
            $cells{$col} = $val if defined $val && length($val);
        }
        $callback->($rnum, \%cells);
    }
}

# Returns an ordered arrayref of { name => sheet name, target => "xl/worksheets/sheetN.xml" }
# for every sheet in the workbook, resolving each sheet's r:id through
# xl/_rels/workbook.xml.rels — the technically-correct way to find which
# worksheetN.xml file backs a given sheet name (position in <sheets> is not
# guaranteed to match the worksheet file number, even though it happens to
# for the files seen so far in this project).
sub read_workbook_sheets {
    my ($zip_path) = @_;

    my $wb;
    {
        open(my $fh, '-|:encoding(UTF-8)', 'unzip', '-p', $zip_path, 'xl/workbook.xml')
            or die "unzip failed for $zip_path (xl/workbook.xml): $!";
        local $/;
        $wb = <$fh>;
        close $fh;
    }
    return [] unless defined $wb;

    my @sheet_refs; # [{name, rid}]
    while ($wb =~ /<sheet\b([^>]*)\/>/gs) {
        my $attrs = $1;
        my ($name) = $attrs =~ /name="([^"]*)"/;
        my ($rid)  = $attrs =~ /r:id="([^"]*)"/;
        next unless defined $name && defined $rid;
        push @sheet_refs, { name => decode_xml($name), rid => $rid };
    }

    my %rid_to_target;
    {
        open(my $fh, '-|:encoding(UTF-8)', 'unzip', '-p', $zip_path, 'xl/_rels/workbook.xml.rels')
            or die "unzip failed for $zip_path (xl/_rels/workbook.xml.rels): $!";
        local $/;
        my $rels = <$fh>;
        close $fh;
        while ($rels =~ /<Relationship\b([^>]*)\/>/gs) {
            my $attrs = $1;
            my ($id)     = $attrs =~ /Id="([^"]*)"/;
            my ($target) = $attrs =~ /Target="([^"]*)"/;
            next unless defined $id && defined $target;
            $target = "xl/$target" unless $target =~ m{^xl/} || $target =~ m{^/};
            $target =~ s{^/}{};
            $rid_to_target{$id} = $target;
        }
    }

    my @out;
    for my $s (@sheet_refs) {
        my $target = $rid_to_target{ $s->{rid} };
        next unless defined $target;
        push @out, { name => $s->{name}, target => $target };
    }
    return \@out;
}

1;
