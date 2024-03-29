#! /usr/bin/python
#
# (C) 2016 jw@owncloud.com
#
# tar2pack.py automates package generation for the openbuildservice.
# It populates a folder (named after the pakcage PACKNAME) with downloaded tar archive and 
# metadata generated from the templates.
#
# The tar  archive name is parsed to derive several template variables:
#  PACKNAME VERSION PRERELEASE
# All (other) variables can be overwritten with -d option.
# 
# Intended usage:
#
# osc co ce:9.0 owncloud-files
# osc co ce:9.0 owncloud
# cd ce:9.0:testing
# tar2pack.py http://download.owncloud.org/community/owncloud-9.0.0RC1.tar.bz2 -d PACKNAME=owncloud-files -d SOURCE_TAR_TOP_DIR=owncloud
# tar2pack.py http://download.owncloud.org/community/owncloud-9.0.0RC1.tar.bz2
# (cd owncloud-files; osc addremove; osc ci)
# (cd owncloud; osc addremove; osc ci)

# Requires: python, wget, svn
#
#
# 2016-03-14: V0.1  jw: unfinished draft.
# 2016-03-15: V0.2  jw: preparing environment
# 2016-03-16: V0.3  jw: templatizing done.
# 2016-03-17: V0.4  jw: added more command line options, copied more code from obs-new-tar.
#                       Code complete. Ready for testing!
# 2016-03-21: V0.5  jw: added -O, -m -- no more implicit outdir creation.
#                       added -[% BUILDRELEASE_DEB %] to builtin changelog entry template.
#                       added which() to allow a helpful error, when svn is not there.
#                       Ignoring bogus directories in outdir, instead of failing during removal.
# 2016-03-22: V0.6  jw: parse nightly tar names correctly.
# 2016-03-23: V0.7  jw: SOURCE_TAR_TOP_DIR derived from inspecting tar-archive.
# 2016-03-29: V0.8  jw: With -O we default PACKNAME to the last component of its realpath.
# 2016-03-30: V0.9  jw: ported to python3:
#                        - all print() with parens,
#                        - all data read/write as binary open(file, encoding="latin-1")
# 2016-04-01: 0.10 jw: warn with uppercase in VERSION or PRERELEASE.
#
## TODO: refresh version in dsc file, to be in sync with changelog.
## FIXME: should have a mode to grab all the define variables from an existing specfile.



import sys, time, argparse, subprocess, os, re, tempfile, shutil
# so that we can have encoding='latin-1' spelled out in both python2 and python3
from io import open

argv0 = 'obs_integration/tar2pack.py'
def_template_dir = 'http://github.com/owncloud/administration/tree/master/jenkins/obs_integration/templates'
def_msg="Update to version [% VERSION_DEB %]"

def subst_variables(text, subst, filename=False):
  def subst_cb(m):
    var = m.group(1)
    if not var in subst:
      print("ERROR: '"+ text + "' refers undefined variable [% "+var+" %], please try with -d")
    return subst[var]
  if filename:
    text = re.sub(r'__([A-Z][A-Z_\d]+)__', subst_cb, text)
  else:
    text = re.sub(r'\[%\s*(\w+)\s*%\]', subst_cb, text)
  return text


def known_sources_spec(spec_file_body):
  src = []
  for m in re.finditer(r'^Source\d+:\s*(\S+)', spec_file_body, flags=re.M):
    name = m.group(1)
    src.append(re.sub(r'.*/','', name))
  return src


### functions copied from obs-new-tar.py

def edit_changes(file, data, msg="Update to version [% VERSION_DEB %]"):
  """
    Prepend the most simplistic but syntactically correct debian changelog entry.
    No changelog body text.
    If an identical entry (except for the timestamp) is already there,
    we just update the timestamp.
  """
  entry_fmt = """-------------------------------------------------------------------
[% DATE_RPM %] - [% MAINTAINER_EMAIL %]

- """+msg+"""

"""
  entry = subst_variables(entry_fmt, data)

  txt = ''
  if os.path.isfile(file):
    txt = open(file, encoding="latin-1").read()

  txt2 = re.sub(r'^.*\n','', txt)
  txt2 = re.sub(r'^.*\n','', txt2)	# cut away first 2 lines.
  ent2 = re.sub(r'^.*\n','', entry)
  ent2 = re.sub(r'^.*\n','', ent2)	# cut away first 2 lines.
  if txt2.startswith(ent2):
    txt = txt2[len(ent2):]
  txt = entry + txt
  out=open(file, "w", encoding="latin-1")
  out.write(txt)
  out.close()


def edit_debchangelog(file, data, msg="Update to version [% VERSION_DEB %]"):
  """
    Prepend the most simplistic but syntactically correct debian changelog entry.
    No changelog body text.
    If an identical entry (except for the timestamp) is already there,
    we just update the timestamp.
  """
  entry_fmt = """[% PACKNAME %] ([% VERSION_DEB %]-[% BUILDRELEASE_DEB %]) stable; urgency=low

  * """+msg+"""

 -- [% MAINTAINER_NAME %] <[% MAINTAINER_EMAIL %]>  """
  entry = subst_variables(entry_fmt, data)

  txt = ''
  if os.path.isfile(file):
    txt = open(file, encoding="latin-1").read()

  if txt.startswith(entry):
    txt = txt[len(entry):]
    txt = re.sub(r'^.*','', txt)		# zap the timestamp
    txt = re.sub(r'^[\s*\n]*','', txt, re.M)	# zap leading newlines and whitespaces
  entry += data['DATE_DEB'] + "\n\n"
  txt = entry + txt
  out=open(file, "w", encoding="latin-1")
  out.write(txt)
  out.close()


def parse_osc_user(data):
  """
    osc user
    jw: "Juergen Weigert" <jw@owncloud.com>
  """
  txt=run_osc(["user"],redirect=True)
  m = re.match(r'(.*?):\s"(.*?)"\s+<(.*?)>', txt)
  if m is None:
    print("Error: osc user failed.")
    sys.exit(0)
  data['LOGNAME'] = m.group(1)
  data['MAINTAINER_NAME'] = m.group(2)
  data['MAINTAINER_EMAIL'] = m.group(3)


def run_osc(args, redirect=False):
  osc = ['osc']
  if os.environ.get('OSCPARAM') is not None:
    osc += os.environ.get('OSCPARAM').split(' ')
  return run( osc + args, redirect=redirect )

def which(program):
    """
      FROM: http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python#377028
    """
    import os
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None

# Keep in sync with obs-new-tar.py internal_tar2obs.py obs_docker_install.py
def run(args, input=None, redirect=None, redirect_stdout=True, redirect_stderr=True, return_tuple=False, return_code=False, tee=False):
  """
     make the subprocess monster usable
  """

  if redirect is not None:
    redirect_stderr = redirect
    redirect_stdout = redirect

  if redirect_stderr:
    redirect_stderr=subprocess.PIPE
  else:
    redirect_stderr=sys.stderr

  if redirect_stdout:
    redirect_stdout=subprocess.PIPE
  else:
    redirect_stdout=sys.stdout

  in_redirect=""
  in_fd=None
  if input is not None:
    in_fd = subprocess.PIPE
    in_redirect=" (<< '%s')" % input

  if verbose: print("+ %s%s" % (args, in_redirect))
  p = subprocess.Popen(args, stdin=in_fd, stdout=redirect_stdout, stderr=redirect_stderr)
 
  (out,err) = p.communicate(input=input)
  # It comes as bytes[] in python3. We want utf-8 or latin-1 strings. 
  # Today latin-1, FIXME: that should be a parameter.
  if out: 
    try:
      out = out.decode('latin-1', errors='backslashreplace')
    except:
      out = repr(out)
  if err: 
    try:
      err = err.decode('latin-1', errors='backslashreplace')
    except:
      err = repr(err)

  # Note. repr() uses backslashreplace, and could be reverted like this:
  #   txt = txt.replace('\\xc3\\xbc', '\xc3\xbc')

  if tee:
    if tee == True: tee=sys.stdout
    if out: print >>tee, " "+ out
    if err: print >>tee, " STDERROR: " + err

  if return_code:  return p.returncode
  if return_tuple: return (out,err,p.returncode)
  if err and out:  return out + "\nSTDERROR: " + err
  if err:          return "STDERROR: " + err
  return out


ap=argparse.ArgumentParser(description="""deb/rpm package generator, using a tar-archive and templates. 
PACKNAME and VERSION are derived from the tar-archive name unless explicitly specified.
""", epilog="""Typical usage with obs checkouts
--------------------------------

cd ce:9.0:testing/owncloud-files
osc up
"""+sys.argv[0]+""" -v -O . https://download.owncloud.org/community/testing/owncloud-9.0.1RC1.tar.bz2
osc diff
osc ci
""", formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('url', type=str, help="tar archive (file or) url to put into this package")
ap.add_argument('-d', '--define', action="append", metavar="KEY=VALUE", help="Specify name=value for template variables. Default: derive from url")
ap.add_argument('-n', '--name', metavar="PACKNAME", help="same as -d PACKNAME=... This defines the name of the package. Default: If no explicit PACKNAME is given, it is derived from -O (if available) or from the tar-archive name.")
ap.add_argument('-e', '--email', metavar="MAINTAINER_EMAIL", help="same as -d MAINTAINER_EMAIL=...; used when updating changelogs. Default: from osc user, if available.")
ap.add_argument('-t', '--template-dir', metavar="TEMPLATE-DIR", default=def_template_dir, help="directory where templates are. Also supports a github repository URL or '../tree/master/..' subdirectory URL")
ap.add_argument('-v', '--verbose', action='store_true', help="Be more verbose. Default: quiet")
ap.add_argument('-k', '--keepfiles', action='store_true', help="Keep unknown files in package. Default: remove them.")
ap.add_argument('-O', '--outdir', help="Define output directory. This also provides a default for PACKNAME. Default: subdirectoy PACKNAME and PACKNAME derived fro tar-archive name.")
ap.add_argument('-m', '--message', help="Define the commit and changelog message. Default: "+re.sub('%', '%%', def_msg), default=def_msg)
args=ap.parse_args()
# print args

verbose = args.verbose
define = {}
try:
  parse_osc_user(define)
except:
  pass	# survive without osc too.

# shortcut define options
if args.define is None: args.define = []
if args.name: args.define.append("PACKNAME=" + args.name)
if args.email: args.define.append("MAINTAINER_EMAIL=" + args.email)

# all -d define options
if args.define:
  for d in args.define:
    (key,val) = d.split('=')
    define[key] = val

if not 'PACKNAME' in define and args.outdir:
  full = os.path.abspath(args.outdir)
  define['PACKNAME'] = full.split('/')[-1]

# owncloud-9.1.0prealpha.20160322.tar.bz2
# (None, 'owncloud', '9.1.0', 'prealpha.20160322', 'tar.bz2', '.bz2')
#
# http://download.owncloud.org/community/owncloud-9.0.0RC1.tar.bz2
# ('http://download.owncloud.org/community/', 'owncloud', '9.0.0', 'rc1', 'tar.bz2', '.bz2')
#              1     2        3                  4                 5   6
m = re.match(r'(.*/)?(.*?)[_-](\d[\d\.]*?)[\.~-]?([a-z]+[\d\.]*)?\.(tar(\.\w+)?|tgz|zip)$', args.url, flags=re.IGNORECASE)
if m:
  if not 'SOURCE_BASE' in define: define['SOURCE_BASE'] = m.group(2)
  if not 'PACKNAME'    in define: define['PACKNAME']    = m.group(2)
  if not 'VERSION'     in define: define['VERSION']     = (m.group(3) or '').lower()	# enforce lower case for safe version compare
  if not 'PRERELEASE'  in define: define['PRERELEASE']  = (m.group(4) or '').lower()	# enforce lower case for safe version compare
  if define['VERSION'] != m.group(3):
    print("Warning: Version number in tar '"+m.group(3)+"' differs from VERSION="+define['VERSION'])
    print("Waiting 3 seconds for CTRL-C")
    time.sleep(5)
else:
  print("Warning: cannot parse PACKNAME, VERSION, PRERELEASE from tar-name: "+args.url)
  print("Waiting 3 seconds for CTRL-C")
  time.sleep(5)

# print m.groups()

if not 'PRERELEASE' in define or define['PRERELEASE'] == None or define['PRERELEASE'] == '': 
  define['PRERELEASE'] = '%nil'
if not 'BUILDRELEASE_DEB' in define:
  define['BUILDRELEASE_DEB'] = '1'
if not 'VERSION_DEB' in define:
  version_deb = define['VERSION']
  if define['PRERELEASE'] != '%nil': version_deb = define['VERSION'] + '~' + define['PRERELEASE']
  define['VERSION_DEB'] = re.sub('-', '_', version_deb)

if define['VERSION'].lower() != define['VERSION']:
  print("Warning: Version comparison is case sensitive. Please use all lower case with VERSION")
  time.sleep(5)

if define['PRERELEASE'].lower() != define['PRERELEASE']:
  print("Warning: Version comparison is case sensitive. Please use all lower case with PRERELEASE")
  time.sleep(5)

#								Thu Jun  4 17:14:46 UTC 2015
if not 'DATE_RPM' in define: define['DATE_RPM'] = time.strftime("%a %b %e %H:%M:%S %Z %Y")
#                         					"Tue, 02 Jun 2015 14:30:50 +0200"
if not 'DATE_DEB' in define: define['DATE_DEB'] = time.strftime("%a, %d %b %Y %H:%M:%S %z")

# so that we can override it with -d SOURCE_TAR_URL=owncloud-%{base_version}%{prerelease}.tar.bz2
if not 'SOURCE_TAR_URL' in define:
  # make sure we have no credentials in SOURCE_TAR_URL
  define['SOURCE_TAR_URL'] = re.sub('://[^@]+@', '://', args.url)


# automatic variables that cannot be overwritten:
define['VERSION_MM'] = re.sub(r'^([^\.]+\.[^\.]+).*$', "\g<1>", define['VERSION'])

if verbose: print(define)

## find templates
template_base = args.template_dir
if re.match('^https?://', args.template_dir):
  # it is an url
  template_base = tempfile.mkdtemp(prefix='tar2pack_')
  if verbose: print(args.template_dir, "->", template_base)
  svn_url = re.sub('/tree/master/', '/trunk/', args.template_dir)
  svn_co = ['svn', 'co', '--non-interactive']
  if not verbose: svn_co.append('--quiet')
  if not which(svn_co[0]):
    print("Error: cannot find svn binary in path. Do you have package subversion installed?")
    print("       (or use -t with a local copy of the templates)")
    sys.exit(0)
  run(svn_co + [svn_url, template_base])

template_dir = template_base
for d in (define['PACKNAME'], define['VERSION_MM'], define['VERSION'], 'v'+re.sub('\.', '_', define['VERSION'])):
  if verbose: print("try subdir "+d+" ... ")
  if os.path.isdir(template_dir + '/' + d):
    template_dir = template_dir + '/' + d
    if verbose: print(" -> OK.")
  else:
    if verbose: print(" -> not found.")

if verbose: print(template_dir)
for d in os.listdir(template_dir):
  if os.path.isdir(template_dir+'/'+d):
    print(template_dir + " is not a template directory: contains subdirectory '"+d+"'")
    print("... or template base '"+template_base+"' had no match for "+define['PACKNAME']+"-"+define['VERSION'])
    exit(1)

## bring in the tar archive
newtarfile=args.url
newtarfile=re.sub(r'.*/','', args.url)

fileslist = { 'debian.changelog':None, define['PACKNAME']+'.changes':None, newtarfile:None }

## read them in all, before writing out one. This way we can print errors before we clobber files.
for file in os.listdir(template_dir):
  if verbose: print("loading template file "+template_dir+"/"+file)
  # need to handle binaries and unknown encodings!
  templ = open(template_dir + '/' + file, encoding='latin-1').read()
  fileslist[subst_variables(file, define, filename=True)] = templ

if re.match('https?://', args.template_dir):
  shutil.rmtree(template_base)


## create destination directory if missing
outdir=args.outdir
if outdir is None: outdir = define['PACKNAME']
if not os.path.isdir(outdir):
  print("ERROR: output directory '"+outdir+"' not there.\nPlease create or try changing with -O")
  sys.exit(1)

if re.search(r'://', args.url):
  r=run(["wget", args.url,"-O",outdir + '/' + newtarfile,"-nv"], redirect=False, return_code=True)
  if r: sys.exit()
else:
  if os.path.abspath(args.url) != os.path.abspath(outdir + '/' + newtarfile):
    # ignore SameFileError. (Without waiting for pyhton 3.4)
    shutil.copyfile(args.url, outdir + '/' + newtarfile)

topdir = run(['sh', '-c', 'tar tf ' + outdir + '/' + newtarfile + ' | head'], redirect=True)
topdir = topdir.split('/', 1)[0]
if not 'SOURCE_TAR_TOP_DIR' in define:
  if topdir and not "STDERROR: " in topdir:
    define['SOURCE_TAR_TOP_DIR'] = topdir
  else:
    # fallback for SOURCE_TAR_TOP_DIR if it cannot be derived from tar archive contents
    if 'SOURCE_BASE' in define: define['SOURCE_TAR_TOP_DIR'] = define['PACKNAME']
    if not 'SOURCE_TAR_TOP_DIR' in define: define['SOURCE_TAR_TOP_DIR'] = define['PACKNAME']

if verbose:
  print("Template variable definitions:")
  for d in sorted(define):
    print("\t"+d+"="+define[d])

## add meta from template,
## templatize after pulling tar source, so that we have its SOURCE_TAR_TOP_DIR.
for file in fileslist:
  if fileslist[file] is not None:
    f = open(outdir + '/' + file, 'w', encoding="latin-1")
    body = subst_variables(fileslist[file], define)
    f.write(body)
    f.close()

    ## also register known sources in the fileslist, so that we can keep them too.
    if (re.search('\.spec$', file)):
      for src in known_sources_spec(body):
        if verbose: print(file+": seen source "+src)
        if not src in fileslist:
          fileslist[src] = None


## clean out all old metafiles.
if not args.keepfiles:
  for file in os.listdir(outdir):
    if not file in fileslist:
      if os.path.isfile(outdir+'/'+file):
        if verbose: print(outdir + ": removing old "+file)
        os.unlink(outdir+'/'+file)
      else:
        print("Ignoring bogus directory: "+file)

## TODO:refresh other sources listed in spec, if url specified
## TODO:refresh dsc file

edit_debchangelog(outdir+'/'+"debian.changelog", define, args.message)
edit_changes(outdir+'/'+define['PACKNAME']+".changes", define, args.message)

exit(0)

