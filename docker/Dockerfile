# This Dockerfile will install some additional packages on top of standard FEniCS dev image
# Some of these are necessary to run stubs, others are for convenience
# Some settings (bash aliases and vim) are also set here
#
# To build the image, run in the main stubs directory:
# $ docker build -t stubs:latest -f Dockerfile .
# To run the image (with default settings, e.g. mounting your home directory):
# $ docker run -ti --name stubs --init -p 8080:8888 -v $HOME:/home/fenics/shared stubs:latest

# Base fenics dev image
FROM quay.io/fenicsproject/dev

# Install desired packages using apt-get
RUN apt-get -qq update && \
    apt-get -qq -y install \
    curl \
    vim \
    htop \
    bpython && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Install desired packages using pip
# *not sure why, but when run in a single line the dependencies for stubs aren't installed
# (e.g. upgrade numpy from version 13.x to 16.x)
RUN python3 -m pip install meshio
RUN python3 -m pip install bpython
RUN python3 -m pip install gmsh
RUN python3 -m pip install fenics-stubs
#RUN python3 -m pip install \
#    meshio \
#    bpython \
#    gmsh \
#    fenics-stubs

# bashrc settings (this appends to the top of the file)
RUN printf \
"# colored terminal output\n\
export TERM=xterm-256color\n" | cat - $FENICS_HOME/.bashrc > temp && \
mv temp $FENICS_HOME/.bashrc

# Bash aliases
RUN printf \
"# Our bash aliases\n\
alias ..='cd ..'\n\
alias ...='cd ../..'\n\
alias ....='cd ../../..'\n\
alias python='python3'\n\
alias bpython='python3 -m bpython'\n\
alias sourceme='source ~/.bashrc'\n\
alias vimbash='vim ~/.bashrc'\n\
alias vimalias='vim ~/.bash_aliases'\n\
alias vimrc='vim ~/.vimrc'" >> $FENICS_HOME/.bash_aliases

# vimrc settings
RUN printf \
"\" Our vimrc settings\n\
syntax on\n\
filetype plugin indent on\n\
set tabstop=4\n\
set shiftwidth=4\n\
set expandtab\n\
set hlsearch\n\
colorscheme desert\n\
inoremap kj <Esc>\n\
vnoremap x \"_x\n\
nnoremap x \"_x\n\
vnoremap c \"_c\n\
nnoremap c \"_c\n\
set visualbell\n\
set t_vb=\n\
set number\n\
set colorcolumn=120\n\
highlight ColorColumn ctermbg=7" >> $FENICS_HOME/.vimrc

# source bashrc
RUN ["/bin/bash", "-c", "source $FENICS_HOME/.bashrc"]
